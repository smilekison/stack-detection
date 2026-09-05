from core.technology_catalog import MANIFEST_ECOSYSTEMS, SOURCE_EXTENSIONS, ecosystem_for_manifest


def test_major_ecosystems_have_manifest_or_build_markers():
    expected = {
        "package.json": "node", "deno.json": "deno", "pyproject.toml": "python", "go.mod": "go",
        "Cargo.toml": "rust", "pom.xml": "jvm", "build.gradle": "jvm", "build.sbt": "scala",
        "composer.json": "php", "Gemfile": "ruby", "mix.exs": "elixir", "rebar.config": "erlang",
        "Package.swift": "swift", "pubspec.yaml": "dart", "stack.yaml": "haskell", "CMakeLists.txt": "cpp",
        "meson.build": "cpp", "project.clj": "clojure",
    }
    for name, ecosystem in expected.items():
        assert ecosystem_for_manifest(name) == ecosystem


def test_common_source_languages_are_distinguished():
    for suffix, language in {
        ".ts":"typescript", ".tsx":"typescript", ".py":"python", ".go":"go", ".rs":"rust",
        ".java":"java", ".kt":"kotlin", ".scala":"scala", ".cs":"csharp", ".fs":"fsharp",
        ".php":"php", ".rb":"ruby", ".ex":"elixir", ".erl":"erlang", ".swift":"swift",
        ".dart":"dart", ".hs":"haskell", ".clj":"clojure", ".c":"c", ".cpp":"cpp", ".lua":"lua",
        ".pl":"perl", ".jl":"julia", ".zig":"zig", ".nim":"nim", ".cr":"crystal",
    }.items():
        assert SOURCE_EXTENSIONS[suffix] == language
