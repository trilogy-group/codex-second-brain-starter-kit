#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


CODE_EXTENSIONS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".rb",
    ".go",
    ".swift",
    ".m",
    ".mm",
    ".h",
    ".sql",
    ".py",
    ".yml",
    ".yaml",
    ".json",
    ".graphql",
    ".gql",
}
SPECIAL_CODE_FILES = {"Dockerfile", "Gemfile", "Podfile", "Fastfile", "Rakefile", "package.json"}
IGNORED_DIRS = {".git", "node_modules", "Pods", "vendor", "dist", "build", "__pycache__", ".next", ".cache"}

CLASS_PATTERNS = (
    re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]*)\b"),
    re.compile(r"\bmodule\s+([A-Z][A-Za-z0-9_:]*)\b"),
    re.compile(r"\btype\s+([A-Z][A-Za-z0-9_]*)\s+(?:struct|interface)\b"),
    re.compile(r"\binterface\s+([A-Z][A-Za-z0-9_]*)\b"),
    re.compile(r"@interface\s+([A-Z][A-Za-z0-9_]*)\b"),
)
FUNCTION_PATTERNS = (
    re.compile(r"\bexport\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\b(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\bfunc\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\bdef\s+([A-Za-z_][A-Za-z0-9_!?=]*)\s*(?:\(|$)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_,\s]+)\s*=>"),
)
TYPE_PATTERNS = (
    re.compile(r"\btype\s+([A-Z][A-Za-z0-9_]*)\s*="),
    re.compile(r"\benum\s+([A-Z][A-Za-z0-9_]*)\b"),
    re.compile(r"\b(?:type|input|enum|interface)\s+([A-Z][A-Za-z0-9_]*)\b"),
)
SQL_OBJECT_RE = re.compile(r"\b(?:CREATE|ALTER)\s+(?:TABLE|VIEW|INDEX|FUNCTION|PROCEDURE)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)
ENV_RE = re.compile(r"(?:ENV\[['\"]([^'\"]+)['\"]\]|process\.env\.([A-Za-z_][A-Za-z0-9_]*)|os\.getenv\(['\"]([^'\"]+)['\"]\)|os\.Getenv\(['\"]([^'\"]+)['\"]\)|System\.getenv\(['\"]([^'\"]+)['\"]\))")
CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*\(")
CALL_STOPWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "function",
    "def",
    "class",
    "describe",
    "it",
    "test",
}


def default_code_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("code_intelligence") or {})
    return {
        "max_files_per_repo": int(configured.get("max_files_per_repo", 1200)),
        "include_git_history": bool(configured.get("include_git_history", True)),
        "include_tests": bool(configured.get("include_tests", True)),
        "include_dependency_graph": bool(configured.get("include_dependency_graph", True)),
    }


def unique(items: list[str], limit: int = 80) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = re.sub(r"\s+", " ", str(item)).strip()
        key = value.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def is_code_like(path: Path) -> bool:
    return path.name in SPECIAL_CODE_FILES or path.suffix.lower() in CODE_EXTENSIONS


def language_for_path(path: Path) -> str:
    if path.name == "Dockerfile":
        return "Dockerfile"
    if path.name in {"Gemfile", "Podfile", "Fastfile", "Rakefile"}:
        return "Ruby DSL"
    return {
        ".js": "JavaScript",
        ".jsx": "JSX",
        ".ts": "TypeScript",
        ".tsx": "TSX",
        ".rb": "Ruby",
        ".go": "Go",
        ".swift": "Swift",
        ".m": "Objective-C",
        ".mm": "Objective-C++",
        ".h": "C/Objective-C header",
        ".sql": "SQL",
        ".py": "Python",
        ".yml": "YAML",
        ".yaml": "YAML",
        ".json": "JSON",
        ".graphql": "GraphQL",
        ".gql": "GraphQL",
    }.get(path.suffix.lower(), "Code")


def collect_code_files(repo_path: Path, max_files: int) -> list[Path]:
    files: list[Path] = []
    if not repo_path.exists():
        return files
    for path in sorted(repo_path.rglob("*")):
        if len(files) >= max_files:
            break
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file() and is_code_like(path):
            files.append(path)
    return files


def extract_symbols(text: str) -> dict[str, list[str]]:
    classes: list[str] = []
    functions: list[str] = []
    types: list[str] = []
    for pattern in CLASS_PATTERNS:
        classes.extend(match.group(1) for match in pattern.finditer(text))
    for pattern in FUNCTION_PATTERNS:
        functions.extend(match.group(1) for match in pattern.finditer(text))
    for pattern in TYPE_PATTERNS:
        types.extend(match.group(1) for match in pattern.finditer(text))
    types.extend(match.group(1) for match in SQL_OBJECT_RE.finditer(text))
    return {
        "classes": unique(classes, 40),
        "functions": unique(functions, 60),
        "types": unique(types, 60),
    }


def extract_imports(text: str, language: str) -> list[str]:
    imports: list[str] = []
    imports.extend(match.group(1) for match in re.finditer(r"\bimport\s+(?:[^'\"]+\s+from\s+)?['\"]([^'\"]+)['\"]", text))
    imports.extend(match.group(1) for match in re.finditer(r"\brequire\(['\"]([^'\"]+)['\"]\)", text))
    imports.extend(match.group(1) for match in re.finditer(r"^\s*require\s+['\"]([^'\"]+)['\"]", text, re.MULTILINE))
    imports.extend(match.group(1) for match in re.finditer(r"^\s*from\s+([A-Za-z0-9_.]+)\s+import\b", text, re.MULTILINE))
    imports.extend(match.group(1) for match in re.finditer(r"^\s*import\s+([A-Za-z0-9_.]+)\b", text, re.MULTILINE))
    imports.extend(match.group(1) for match in re.finditer(r"^\s*import\s+([A-Za-z0-9_./-]+)$", text, re.MULTILINE))
    if language == "Ruby DSL":
        imports.extend(match.group(1) for match in re.finditer(r"^\s*gem\s+['\"]([^'\"]+)['\"]", text, re.MULTILINE))
    return unique(imports, 80)


def extract_calls(text: str) -> list[str]:
    calls = [
        match.group(1)
        for match in CALL_RE.finditer(text)
        if match.group(1).split(".", 1)[0] not in CALL_STOPWORDS
    ]
    return unique(calls, 100)


def extract_routes(text: str, relative_path: str) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for match in re.finditer(r"\b(get|post|put|patch|delete)\s+['\"]([^'\"]+)['\"]", text, re.IGNORECASE):
        routes.append({"method": match.group(1).upper(), "path": match.group(2), "source": relative_path})
    for match in re.finditer(r"\b(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]", text, re.IGNORECASE):
        routes.append({"method": match.group(1).upper(), "path": match.group(2), "source": relative_path})
    for match in re.finditer(r"@(?:app|router)\.(get|post|put|patch|delete|route)\(\s*['\"]([^'\"]+)['\"](?:,\s*methods=\[([^\]]+)\])?", text, re.IGNORECASE):
        method = match.group(1).upper()
        if method == "ROUTE" and match.group(3):
            method = ",".join(re.findall(r"['\"]([A-Z]+)['\"]", match.group(3))) or "ROUTE"
        routes.append({"method": method, "path": match.group(2), "source": relative_path})
    for match in re.finditer(r"http\.HandleFunc\(\s*['\"]([^'\"]+)['\"]", text):
        routes.append({"method": "HTTP", "path": match.group(1), "source": relative_path})
    for match in re.finditer(r"\bresources\s+:([A-Za-z0-9_]+)", text):
        routes.append({"method": "REST", "path": f"/{match.group(1)}", "source": relative_path})
    return routes[:120]


def extract_schemas(text: str, path: Path, relative_path: str) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for match in re.finditer(r"\bcreate_table\s+['\"]?:?([A-Za-z0-9_]+)['\"]?", text):
        schemas.append({"kind": "table", "name": match.group(1), "source": relative_path})
    for match in SQL_OBJECT_RE.finditer(text):
        schemas.append({"kind": "sql-object", "name": match.group(1), "source": relative_path})
    for match in re.finditer(r"\b(?:type|input|enum|interface)\s+([A-Z][A-Za-z0-9_]*)\b", text):
        schemas.append({"kind": "graphql", "name": match.group(1), "source": relative_path})
    for match in re.finditer(r"\b(?:interface|type)\s+([A-Z][A-Za-z0-9_]*)\b", text):
        schemas.append({"kind": "type", "name": match.group(1), "source": relative_path})
    if path.suffix.lower() in {".json", ".yml", ".yaml"}:
        parsed = parse_structured_text(text, path)
        if isinstance(parsed, dict):
            if "openapi" in parsed or "swagger" in parsed:
                schemas.append({"kind": "openapi", "name": path.name, "source": relative_path})
                for name in sorted((parsed.get("components") or {}).get("schemas") or {})[:80]:
                    schemas.append({"kind": "openapi-schema", "name": name, "source": relative_path})
                for route in sorted((parsed.get("paths") or {}).keys())[:120]:
                    schemas.append({"kind": "openapi-path", "name": route, "source": relative_path})
            elif "dependencies" in parsed or "devDependencies" in parsed:
                schemas.append({"kind": "package-manifest", "name": path.name, "source": relative_path})
    return schemas[:160]


def parse_structured_text(text: str, path: Path) -> Any:
    try:
        if path.suffix.lower() == ".json" or path.name == "package.json":
            return json.loads(text)
        if path.suffix.lower() in {".yml", ".yaml"} and yaml is not None:
            return yaml.safe_load(text)
    except Exception:
        return None
    return None


def structured_parse_error(text: str, path: Path) -> str | None:
    try:
        if path.suffix.lower() == ".json" or path.name == "package.json":
            json.loads(text)
        elif path.suffix.lower() in {".yml", ".yaml"} and yaml is not None:
            yaml.safe_load(text)
    except Exception as exc:
        return str(exc)
    return None


def extract_tests(text: str, relative_path: str) -> list[dict[str, str]]:
    lower = relative_path.lower()
    anchors: list[dict[str, str]] = []
    if any(term in lower for term in ("test", "spec", "__tests__", "xctest")):
        anchors.append({"kind": "test-file", "name": Path(relative_path).name, "source": relative_path})
    for match in re.finditer(r"\b(?:describe|it|test)\s*\(\s*['\"]([^'\"]+)['\"]", text):
        anchors.append({"kind": "js-test", "name": match.group(1), "source": relative_path})
    for match in re.finditer(r"\bRSpec\.describe\s+([A-Za-z0-9_:]+)", text):
        anchors.append({"kind": "rspec", "name": match.group(1), "source": relative_path})
    for match in re.finditer(r"\bdef\s+(test_[A-Za-z0-9_]+)", text):
        anchors.append({"kind": "python-test", "name": match.group(1), "source": relative_path})
    return anchors[:80]


def extract_env_vars(text: str) -> list[str]:
    values: list[str] = []
    for match in ENV_RE.finditer(text):
        values.extend(group for group in match.groups() if group)
    return unique(values, 80)


def extract_dependencies(path: Path, text: str, imports: list[str]) -> list[str]:
    deps = list(imports)
    parsed = parse_structured_text(text, path)
    if isinstance(parsed, dict) and path.name == "package.json":
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            values = parsed.get(section)
            if isinstance(values, dict):
                deps.extend(str(name) for name in values)
    if path.name == "Gemfile":
        deps.extend(match.group(1) for match in re.finditer(r"^\s*gem\s+['\"]([^'\"]+)['\"]", text, re.MULTILINE))
    return unique(deps, 120)


def migration_signals(relative_path: str, text: str) -> list[str]:
    signals: list[str] = []
    if "migration" in relative_path.lower() or re.search(r"\b(?:create_table|alter_table|CREATE\s+TABLE|ALTER\s+TABLE)\b", text, re.IGNORECASE):
        signals.append("database migration or schema change")
    if "schema" in relative_path.lower() or "openapi" in text.lower() or "graphql" in text.lower():
        signals.append("schema or contract surface")
    return unique(signals, 20)


def analyze_file(repo_name: str, repo_path: Path, path: Path, git_metrics: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    relative_path = path.relative_to(repo_path).as_posix()
    try:
        text = path.read_text(errors="ignore")
        parse_quality = "complete"
        parser_errors: list[str] = []
    except Exception as exc:  # pragma: no cover - uncommon but intentionally non-fatal
        text = ""
        parse_quality = "partial"
        parser_errors = [str(exc)]
    language = language_for_path(path)
    structured_error = structured_parse_error(text, path) if text else None
    if structured_error:
        parse_quality = "partial"
        parser_errors.append(structured_error)
    symbols = extract_symbols(text)
    imports = extract_imports(text, language)
    calls = extract_calls(text)
    routes = extract_routes(text, relative_path)
    schemas = extract_schemas(text, path, relative_path)
    tests = extract_tests(text, relative_path)
    env_vars = extract_env_vars(text)
    dependencies = extract_dependencies(path, text, imports)
    migrations = migration_signals(relative_path, text)
    metrics = (git_metrics or {}).get(relative_path, {})
    return {
        "repo": repo_name,
        "relative_path": relative_path,
        "language": language,
        "parse_quality": parse_quality,
        "parser_errors": parser_errors,
        "symbols": symbols,
        "symbol_count": sum(len(values) for values in symbols.values()),
        "imports": imports,
        "calls": calls,
        "routes": routes,
        "route_count": len(routes),
        "schemas": schemas,
        "schema_count": len(schemas),
        "tests": tests,
        "test_anchor_count": len(tests),
        "env_vars": env_vars,
        "migrations": migrations,
        "dependencies": dependencies,
        "dependency_count": len(dependencies),
        "churn_score": int(metrics.get("churn_score", 0)),
        "churn_count": int(metrics.get("churn_count", 0)),
        "recent_edit": metrics.get("recent_edit", ""),
        "owner_candidates": metrics.get("owner_candidates", []),
    }


def collect_git_metrics(repo_path: Path, relative_paths: set[str]) -> dict[str, dict[str, Any]]:
    if not relative_paths or not (repo_path / ".git").exists():
        return {}
    completed = subprocess.run(
        ["git", "-C", str(repo_path), "log", "--name-only", "--format=__COMMIT__|%ad|%an", "--date=short", "--"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        return {}
    churn: Counter[str] = Counter()
    owners: dict[str, Counter[str]] = defaultdict(Counter)
    recent: dict[str, str] = {}
    current_author = ""
    current_date = ""
    touched_in_commit: set[str] = set()
    for raw in [*completed.stdout.splitlines(), "__COMMIT__|END|END"]:
        line = raw.strip()
        if line.startswith("__COMMIT__|"):
            for path in touched_in_commit:
                churn[path] += 1
                if current_author:
                    owners[path][current_author] += 1
                if current_date and current_date > recent.get(path, ""):
                    recent[path] = current_date
            touched_in_commit = set()
            _, current_date, current_author = line.split("|", 2)
            continue
        if line in relative_paths:
            touched_in_commit.add(line)
    return {
        path: {
            "churn_count": churn[path],
            "churn_score": min(10, churn[path]),
            "recent_edit": recent.get(path, ""),
            "owner_candidates": [name for name, _ in owners[path].most_common(3)],
        }
        for path in churn
    }


def graph_from_files(files: list[dict[str, Any]]) -> dict[str, Any]:
    dependency_edges: list[dict[str, str]] = []
    call_edges: list[dict[str, str]] = []
    route_edges: list[dict[str, str]] = []
    schema_edges: list[dict[str, str]] = []
    test_edges: list[dict[str, str]] = []
    for item in files:
        node = f"{item['repo']}/{item['relative_path']}"
        for dep in item["dependencies"][:80]:
            dependency_edges.append({"from": node, "to": dep})
        for call in item["calls"][:80]:
            call_edges.append({"from": node, "to": call})
        for route in item["routes"]:
            route_edges.append({"from": node, "to": f"{route['method']} {route['path']}"})
        for schema in item["schemas"]:
            schema_edges.append({"from": node, "to": f"{schema['kind']}:{schema['name']}"})
        for test in item["tests"]:
            test_edges.append({"from": node, "to": test["name"]})
    return {
        "dependencies": dependency_edges,
        "calls": call_edges,
        "routes": route_edges,
        "schemas": schema_edges,
        "tests": test_edges,
    }


def analyze_repositories(repo_roots: dict[str, Path], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    config = default_code_config(profile)
    files: list[dict[str, Any]] = []
    repo_summaries: list[dict[str, Any]] = []
    for repo_name, repo_path in sorted(repo_roots.items()):
        code_files = collect_code_files(repo_path, config["max_files_per_repo"])
        relative_paths = {path.relative_to(repo_path).as_posix() for path in code_files}
        git_metrics = collect_git_metrics(repo_path, relative_paths) if config["include_git_history"] else {}
        repo_files = [analyze_file(repo_name, repo_path, path, git_metrics=git_metrics) for path in code_files]
        files.extend(repo_files)
        repo_summaries.append(
            {
                "repo": repo_name,
                "path": str(repo_path),
                "files_scanned": len(repo_files),
                "parse_failures": sum(1 for item in repo_files if item["parse_quality"] != "complete"),
                "route_count": sum(item["route_count"] for item in repo_files),
                "schema_count": sum(item["schema_count"] for item in repo_files),
                "test_anchor_count": sum(item["test_anchor_count"] for item in repo_files),
                "dependency_count": sum(item["dependency_count"] for item in repo_files),
                "high_churn_files": [
                    f"{item['repo']}/{item['relative_path']}"
                    for item in sorted(repo_files, key=lambda value: (-value["churn_score"], value["relative_path"]))[:20]
                    if item["churn_score"] > 0
                ],
            }
        )
    graph = graph_from_files(files)
    summary = {
        "parsed_files": len(files),
        "parse_failures": sum(1 for item in files if item["parse_quality"] != "complete"),
        "route_count": len(graph["routes"]),
        "schema_count": len(graph["schemas"]),
        "test_anchor_count": len(graph["tests"]),
        "dependency_edges": len(graph["dependencies"]),
    }
    return {
        "config": config,
        "summary": summary,
        "repos": repo_summaries,
        "files": files,
        "graph": graph,
    }
