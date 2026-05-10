#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import ast
import hashlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generation_performance
import incremental_cache


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
TREE_SITTER_LANGUAGE_BY_SUFFIX = {
    ".rb": "ruby",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".swift": "swift",
    ".m": "objc",
    ".mm": "objc",
    ".h": "objc",
}
TREE_SITTER_SYMBOL_NODES = {
    "class",
    "class_declaration",
    "class_definition",
    "module",
    "module_definition",
    "struct_declaration",
    "interface_declaration",
    "function",
    "function_declaration",
    "function_definition",
    "method",
    "method_definition",
    "method_declaration",
    "arrow_function",
    "lexical_declaration",
    "type_alias_declaration",
    "type_declaration",
    "enum_declaration",
}
TREE_SITTER_IMPORT_NODES = {
    "import_statement",
    "import_declaration",
    "import_from_statement",
    "require",
    "require_call",
}
TREE_SITTER_CALL_NODES = {
    "call",
    "call_expression",
    "method_call",
    "command_call",
    "function_call",
    "invocation",
}


def default_code_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("code_intelligence") or {})
    generation_config = generation_performance.default_generation_config(profile)
    return {
        "max_files_per_repo": int(configured.get("max_files_per_repo", 1200)),
        "include_git_history": bool(configured.get("include_git_history", True)),
        "include_tests": bool(configured.get("include_tests", True)),
        "include_dependency_graph": bool(configured.get("include_dependency_graph", True)),
        "parser_mode": str(configured.get("parser_mode", "ast-when-available")),
        "repo_analysis_workers": generation_config["repo_analysis_workers"],
        "code_analysis_workers": generation_config["code_analysis_workers"],
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


def tree_sitter_language_for_path(path: Path) -> str:
    return TREE_SITTER_LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "")


def get_tree_sitter_parser(language_name: str) -> Any | None:
    if not language_name:
        return None
    try:
        from tree_sitter_languages import get_parser  # type: ignore
    except Exception:
        return None
    try:
        return get_parser(language_name)
    except Exception:
        return None


def node_text(node: Any, text_bytes: bytes) -> str:
    try:
        return text_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def walk_tree_sitter_nodes(root: Any) -> list[Any]:
    nodes: list[Any] = []
    stack = [root]
    while stack:
        node = stack.pop()
        nodes.append(node)
        try:
            children = list(node.children)
        except Exception:
            children = []
        stack.extend(reversed(children))
    return nodes


def first_named_child_text(node: Any, text_bytes: bytes) -> str:
    try:
        named = list(node.named_children)
    except Exception:
        named = []
    for child in named:
        if getattr(child, "type", "") in {"identifier", "constant", "type_identifier", "property_identifier", "field_identifier"}:
            return node_text(child, text_bytes)
    return ""


def tree_sitter_node_name(node: Any, text_bytes: bytes) -> str:
    try:
        name_node = node.child_by_field_name("name")
    except Exception:
        name_node = None
    if name_node is not None:
        value = node_text(name_node, text_bytes)
        if value:
            return value
    return first_named_child_text(node, text_bytes)


def tree_sitter_call_name(node: Any, text_bytes: bytes) -> str:
    try:
        function_node = node.child_by_field_name("function")
    except Exception:
        function_node = None
    if function_node is not None:
        value = node_text(function_node, text_bytes)
        if value:
            return re.sub(r"\s+", " ", value)[:120]
    return first_named_child_text(node, text_bytes) or re.sub(r"\s+", " ", node_text(node, text_bytes))[:120]


def tree_sitter_symbol_kind(node_type: str) -> str:
    if "class" in node_type or "module" in node_type or "struct" in node_type:
        return "class"
    if "type" in node_type or "enum" in node_type or "interface" in node_type:
        return "type"
    return "function"


def extract_tree_sitter_ast(text: str, path: Path, relative_path: str) -> dict[str, Any]:
    language_name = tree_sitter_language_for_path(path)
    if not language_name:
        return {
            "parser_backend": "regex-fallback",
            "ast_node_count": 0,
            "symbols": {"classes": [], "functions": [], "types": []},
            "imports": [],
            "calls": [],
            "symbol_edges": [],
            "call_edges": [],
            "routes": [],
            "parser_limitations": ["No tree-sitter language mapping is configured for this file type."],
        }
    parser = get_tree_sitter_parser(language_name)
    if parser is None:
        return {
            "parser_backend": "regex-fallback",
            "ast_node_count": 0,
            "symbols": {"classes": [], "functions": [], "types": []},
            "imports": [],
            "calls": [],
            "symbol_edges": [],
            "call_edges": [],
            "routes": [],
            "parser_limitations": [f"tree-sitter parser for `{language_name}` is not available; regex extraction was used."],
        }
    text_bytes = text.encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(text_bytes)
    except Exception as exc:
        return {
            "parser_backend": "regex-fallback",
            "ast_node_count": 0,
            "symbols": {"classes": [], "functions": [], "types": []},
            "imports": [],
            "calls": [],
            "symbol_edges": [],
            "call_edges": [],
            "routes": [],
            "parser_limitations": [f"tree-sitter parse failed for `{language_name}`: {exc}"],
        }
    classes: list[str] = []
    functions: list[str] = []
    types: list[str] = []
    imports: list[str] = []
    calls: list[str] = []
    symbol_edges: list[dict[str, Any]] = []
    call_edges: list[dict[str, Any]] = []
    nodes = walk_tree_sitter_nodes(tree.root_node)
    for node in nodes:
        node_type = getattr(node, "type", "")
        if node_type in TREE_SITTER_IMPORT_NODES:
            imports.append(node_text(node, text_bytes))
        if node_type in TREE_SITTER_SYMBOL_NODES:
            name = tree_sitter_node_name(node, text_bytes)
            if name:
                kind = tree_sitter_symbol_kind(node_type)
                if kind == "class":
                    classes.append(name)
                elif kind == "type":
                    types.append(name)
                else:
                    functions.append(name)
                symbol_edges.append(
                    {
                        "kind": kind,
                        "name": name,
                        "source": relative_path,
                        "line_start": int(node.start_point[0]) + 1,
                        "line_end": int(node.end_point[0]) + 1,
                        "parser_backend": f"tree-sitter:{language_name}",
                    }
                )
        if node_type in TREE_SITTER_CALL_NODES:
            name = tree_sitter_call_name(node, text_bytes)
            if name and name.split(".", 1)[0] not in CALL_STOPWORDS:
                calls.append(name)
                call_edges.append(
                    {
                        "from": relative_path,
                        "to": name,
                        "line_start": int(node.start_point[0]) + 1,
                        "line_end": int(node.end_point[0]) + 1,
                        "parser_backend": f"tree-sitter:{language_name}",
                    }
                )
    return {
        "parser_backend": f"tree-sitter:{language_name}",
        "ast_node_count": len(nodes),
        "symbols": {
            "classes": unique(classes, 80),
            "functions": unique(functions, 120),
            "types": unique(types, 120),
        },
        "imports": unique(imports, 120),
        "calls": unique(calls, 160),
        "symbol_edges": symbol_edges[:300],
        "call_edges": call_edges[:500],
        "routes": [],
        "parser_limitations": ["tree-sitter v1 captures syntax anchors and lightweight call edges, not full type-resolved references."],
    }


class PythonAstVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.classes: list[str] = []
        self.functions: list[str] = []
        self.types: list[str] = []
        self.imports: list[str] = []
        self.calls: list[str] = []
        self.routes: list[dict[str, str]] = []
        self.symbol_edges: list[dict[str, Any]] = []
        self.call_edges: list[dict[str, Any]] = []
        self.scope: list[str] = []

    def line_end(self, node: ast.AST) -> int:
        return int(getattr(node, "end_lineno", getattr(node, "lineno", 1)) or 1)

    def symbol_edge(self, kind: str, name: str, node: ast.AST) -> dict[str, Any]:
        return {
            "kind": kind,
            "name": name,
            "source": self.relative_path,
            "line_start": int(getattr(node, "lineno", 1) or 1),
            "line_end": self.line_end(node),
            "parser_backend": "python-ast",
        }

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self.symbol_edges.append(self.symbol_edge("class", node.name, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.symbol_edges.append(self.symbol_edge("function", node.name, node))
        self.routes.extend(self.routes_from_decorators(node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        prefix = "." * int(node.level or 0) + (node.module or "")
        self.imports.extend(f"{prefix}.{alias.name}".strip(".") for alias in node.names)

    def visit_Call(self, node: ast.Call) -> None:
        name = self.call_name(node.func)
        if name and name.split(".", 1)[0] not in CALL_STOPWORDS:
            self.calls.append(name)
            self.call_edges.append(
                {
                    "from": ".".join(self.scope) if self.scope else self.relative_path,
                    "to": name,
                    "source": self.relative_path,
                    "line_start": int(getattr(node, "lineno", 1) or 1),
                    "line_end": self.line_end(node),
                    "parser_backend": "python-ast",
                }
            )
        self.generic_visit(node)

    def call_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = self.call_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""

    def routes_from_decorators(self, node: ast.FunctionDef) -> list[dict[str, str]]:
        routes: list[dict[str, str]] = []
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            name = self.call_name(decorator.func).lower()
            method = name.rsplit(".", 1)[-1].upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "ROUTE"}:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant) or not isinstance(decorator.args[0].value, str):
                continue
            path_value = decorator.args[0].value
            methods = ""
            for keyword in decorator.keywords:
                if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                    values = [item.value for item in keyword.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
                    methods = ",".join(value.upper() for value in values)
            routes.append({"method": methods or method, "path": path_value, "source": self.relative_path})
        return routes


def count_python_ast_nodes(root: ast.AST) -> int:
    return sum(1 for _ in ast.walk(root))


def extract_python_ast(text: str, relative_path: str) -> dict[str, Any]:
    try:
        root = ast.parse(text)
    except SyntaxError as exc:
        return {
            "parser_backend": "regex-fallback",
            "ast_node_count": 0,
            "symbols": {"classes": [], "functions": [], "types": []},
            "imports": [],
            "calls": [],
            "symbol_edges": [],
            "call_edges": [],
            "routes": [],
            "parser_limitations": [f"python ast parse failed: {exc}"],
        }
    visitor = PythonAstVisitor(relative_path)
    visitor.visit(root)
    return {
        "parser_backend": "python-ast",
        "ast_node_count": count_python_ast_nodes(root),
        "symbols": {
            "classes": unique(visitor.classes, 80),
            "functions": unique(visitor.functions, 120),
            "types": unique(visitor.types, 120),
        },
        "imports": unique(visitor.imports, 120),
        "calls": unique(visitor.calls, 160),
        "symbol_edges": visitor.symbol_edges[:300],
        "call_edges": visitor.call_edges[:500],
        "routes": visitor.routes[:120],
        "parser_limitations": ["python ast captures syntax anchors and lightweight call edges, not runtime type-resolved references."],
    }


def extract_ast_intelligence(text: str, path: Path, relative_path: str, parser_mode: str) -> dict[str, Any]:
    if parser_mode == "regex-only":
        return {
            "parser_backend": "regex-fallback",
            "ast_node_count": 0,
            "symbols": {"classes": [], "functions": [], "types": []},
            "imports": [],
            "calls": [],
            "symbol_edges": [],
            "call_edges": [],
            "routes": [],
            "parser_limitations": ["Profile configured parser_mode=regex-only."],
        }
    if path.suffix.lower() == ".py":
        return extract_python_ast(text, relative_path)
    return extract_tree_sitter_ast(text, path, relative_path)


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


def merge_symbols(regex_symbols: dict[str, list[str]], ast_symbols: dict[str, list[str]]) -> dict[str, list[str]]:
    return {
        "classes": unique([*ast_symbols.get("classes", []), *regex_symbols.get("classes", [])], 80),
        "functions": unique([*ast_symbols.get("functions", []), *regex_symbols.get("functions", [])], 120),
        "types": unique([*ast_symbols.get("types", []), *regex_symbols.get("types", [])], 120),
    }


def analyze_file(
    repo_name: str,
    repo_path: Path,
    path: Path,
    git_metrics: dict[str, dict[str, Any]] | None = None,
    parser_mode: str = "ast-when-available",
) -> dict[str, Any]:
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
    ast_intel = extract_ast_intelligence(text, path, relative_path, parser_mode)
    symbols = merge_symbols(extract_symbols(text), ast_intel.get("symbols") or {})
    imports = unique([*ast_intel.get("imports", []), *extract_imports(text, language)], 160)
    calls = unique([*ast_intel.get("calls", []), *extract_calls(text)], 200)
    routes = [
        *ast_intel.get("routes", []),
        *extract_routes(text, relative_path),
    ]
    schemas = extract_schemas(text, path, relative_path)
    tests = extract_tests(text, relative_path)
    env_vars = extract_env_vars(text)
    dependencies = extract_dependencies(path, text, imports)
    migrations = migration_signals(relative_path, text)
    metrics = (git_metrics or {}).get(relative_path, {})
    line_count = len(text.splitlines()) if text else 0
    parser_limitations = list(ast_intel.get("parser_limitations") or [])
    return {
        "repo": repo_name,
        "relative_path": relative_path,
        "absolute_path": str(path),
        "language": language,
        "parse_quality": parse_quality,
        "parser_errors": parser_errors,
        "parser_backend": ast_intel.get("parser_backend", "regex-fallback"),
        "ast_node_count": int(ast_intel.get("ast_node_count", 0) or 0),
        "parser_limitations": parser_limitations,
        "line_start": 1 if line_count else 0,
        "line_end": line_count,
        "symbols": symbols,
        "symbol_count": sum(len(values) for values in symbols.values()),
        "symbol_edges": list(ast_intel.get("symbol_edges") or []),
        "imports": imports,
        "calls": calls,
        "call_edges": list(ast_intel.get("call_edges") or []),
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
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "log", "--name-only", "--format=__COMMIT__|%ad|%an", "--date=short", "--"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
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


def _repo_inputs(repo_item: tuple[str, Path], config: dict[str, Any]) -> dict[str, Any]:
    repo_name, repo_path = repo_item
    code_files = collect_code_files(repo_path, config["max_files_per_repo"])
    relative_paths = {path.relative_to(repo_path).as_posix() for path in code_files}
    git_metrics = collect_git_metrics(repo_path, relative_paths) if config["include_git_history"] else {}
    return {
        "repo_name": repo_name,
        "repo_path": repo_path,
        "code_files": code_files,
        "git_metrics": git_metrics,
    }


def clean_git_repo_head(repo_path: Path) -> tuple[bool, str, str]:
    if not (repo_path / ".git").exists():
        return False, "", "not-a-git-repo"
    try:
        head = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "", f"git-check-failed:{exc}"
    if head.returncode != 0:
        return False, "", "head-unavailable"
    if status.returncode != 0:
        return False, "", "status-unavailable"
    if status.stdout.strip():
        return False, head.stdout.strip(), "dirty-worktree"
    return True, head.stdout.strip(), "clean"


def repo_cache_payload(repo_name: str, repo_path: Path, config: dict[str, Any], clean_head: str) -> dict[str, Any]:
    return {
        "repo": repo_name,
        "path": str(repo_path),
        "head": clean_head,
        "code_intelligence": {
            "max_files_per_repo": config["max_files_per_repo"],
            "include_git_history": config["include_git_history"],
            "include_tests": config["include_tests"],
            "include_dependency_graph": config["include_dependency_graph"],
            "parser_mode": config["parser_mode"],
        },
    }


def _analyze_file_task(task: tuple[str, Path, Path, dict[str, dict[str, Any]], str]) -> dict[str, Any]:
    repo_name, repo_path, path, git_metrics, parser_mode = task
    return analyze_file(repo_name, repo_path, path, git_metrics=git_metrics, parser_mode=parser_mode)


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
        if item.get("call_edges"):
            for edge in item["call_edges"][:120]:
                call_edges.append({"from": f"{item['repo']}/{edge.get('from', item['relative_path'])}", "to": str(edge.get("to", ""))})
        else:
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


def file_cache_payload(
    repo_name: str,
    repo_path: Path,
    path: Path,
    git_metrics: dict[str, dict[str, Any]],
    parser_mode: str,
) -> dict[str, Any]:
    relative_path = path.relative_to(repo_path).as_posix()
    try:
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        content_hash = "unreadable"
    return {
        "repo": repo_name,
        "relative_path": relative_path,
        "content_sha256": content_hash,
        "git_metrics": git_metrics.get(relative_path, {}),
        "parser_mode": parser_mode,
    }


def analyze_repositories(
    repo_roots: dict[str, Path],
    profile: dict[str, Any] | None = None,
    *,
    cache_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    config = default_code_config(profile)
    generation_config = generation_performance.default_generation_config(profile)
    cache = incremental_cache.load_incremental_cache(cache_path) if cache_path and generation_config["incremental_rebuild"] else None
    if cache is not None:
        incremental_cache.reset_stats(cache)
    repo_items = sorted(repo_roots.items())
    repo_workers = config["repo_analysis_workers"]
    with ThreadPoolExecutor(max_workers=repo_workers, thread_name_prefix="basb-repo-analysis") as executor:
        repo_inputs = list(executor.map(lambda item: _repo_inputs(item, config), repo_items))

    repo_inputs.sort(key=lambda item: item["repo_name"])
    file_tasks: list[tuple[str, Path, Path, dict[str, dict[str, Any]], str]] = []
    cached_files: list[dict[str, Any]] = []
    file_payloads: dict[tuple[str, str], dict[str, Any]] = {}
    repo_cache_hits = 0
    repo_cache_misses = 0
    repo_cache_bypassed = 0
    repo_cache_payloads: dict[str, dict[str, Any]] = {}
    repo_cached_names: set[str] = set()
    for item in repo_inputs:
        repo_name = item["repo_name"]
        repo_path = item["repo_path"]
        clean, clean_head, clean_reason = clean_git_repo_head(repo_path)
        repo_payload = repo_cache_payload(repo_name, repo_path, config, clean_head)
        repo_cache_payloads[repo_name] = repo_payload
        repo_cached = (
            incremental_cache.lookup(cache, "code_repo_analysis", repo_name, repo_payload)
            if cache is not None and clean and not force
            else None
        )
        if repo_cached is not None and isinstance(repo_cached.value, dict) and isinstance(repo_cached.value.get("files"), list):
            repo_cache_hits += 1
            repo_cached_names.add(repo_name)
            cached_files.extend(item for item in repo_cached.value["files"] if isinstance(item, dict))
            continue
        if not clean or force:
            repo_cache_bypassed += 1
        elif cache is not None:
            repo_cache_misses += 1
        for path in item["code_files"]:
            relative_path = path.relative_to(item["repo_path"]).as_posix()
            task = (
                repo_name,
                item["repo_path"],
                path,
                item["git_metrics"],
                config["parser_mode"],
            )
            payload = file_cache_payload(*task)
            key = (repo_name, relative_path)
            file_payloads[key] = payload
            cached = (
                incremental_cache.lookup(cache, "code_file_analysis", f"{repo_name}/{relative_path}", payload)
                if cache is not None and not force
                else None
            )
            if cached is not None and isinstance(cached.value, dict):
                cached_files.append(cached.value)
            else:
                file_tasks.append(task)
    file_tasks.sort(key=lambda task: (task[0], task[2].relative_to(task[1]).as_posix()))

    if file_tasks:
        with ThreadPoolExecutor(max_workers=config["code_analysis_workers"], thread_name_prefix="basb-code-analysis") as executor:
            analyzed_files = list(executor.map(_analyze_file_task, file_tasks))
    else:
        analyzed_files = []

    if cache is not None:
        for item in analyzed_files:
            payload = file_payloads[(item["repo"], item["relative_path"])]
            incremental_cache.store(cache, "code_file_analysis", f"{item['repo']}/{item['relative_path']}", payload, item)
        incremental_cache.write_incremental_cache(cache_path, cache)

    files = [*cached_files, *analyzed_files]
    for item in files:
        repo_name = str(item.get("repo") or "")
        relative_path = str(item.get("relative_path") or "")
        repo_path = repo_roots.get(repo_name)
        if repo_path is not None and relative_path and not item.get("absolute_path"):
            item["absolute_path"] = str(repo_path / relative_path)

    files.sort(key=lambda item: (item["repo"], item["relative_path"]))
    if cache is not None:
        files_by_repo_for_cache: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in files:
            files_by_repo_for_cache[item["repo"]].append(item)
        for item in repo_inputs:
            repo_name = item["repo_name"]
            clean, clean_head, _clean_reason = clean_git_repo_head(item["repo_path"])
            if not clean or force or repo_name in repo_cached_names:
                continue
            payload = {**repo_cache_payloads.get(repo_name, {}), "head": clean_head}
            incremental_cache.store(
                cache,
                "code_repo_analysis",
                repo_name,
                payload,
                {"files": files_by_repo_for_cache.get(repo_name, [])},
            )
        incremental_cache.write_incremental_cache(cache_path, cache)

    files_by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in files:
        files_by_repo[item["repo"]].append(item)

    repo_summaries: list[dict[str, Any]] = []
    for item in repo_inputs:
        repo_name = item["repo_name"]
        repo_path = item["repo_path"]
        repo_files = files_by_repo.get(repo_name, [])
        repo_summaries.append(
            {
                "repo": repo_name,
                "path": str(repo_path),
                "files_scanned": len(repo_files),
                "parse_failures": sum(1 for item in repo_files if item["parse_quality"] != "complete"),
                "ast_parsed_files": sum(1 for item in repo_files if item["parser_backend"] != "regex-fallback"),
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
        "ast_parsed_files": sum(1 for item in files if item["parser_backend"] != "regex-fallback"),
        "ast_node_count": sum(int(item.get("ast_node_count", 0)) for item in files),
        "route_count": len(graph["routes"]),
        "schema_count": len(graph["schemas"]),
        "test_anchor_count": len(graph["tests"]),
        "dependency_edges": len(graph["dependencies"]),
        "repo_cache_hits": repo_cache_hits,
        "repo_cache_misses": repo_cache_misses,
        "repo_cache_bypassed": repo_cache_bypassed,
        "cache_hits": int((cache or {}).get("stats", {}).get("skipped_stages", {}).get("code_file_analysis", 0)),
        "cache_misses": int((cache or {}).get("stats", {}).get("misses", 0)) if cache is not None else 0,
    }
    return {
        "config": config,
        "summary": summary,
        "repos": repo_summaries,
        "files": files,
        "graph": graph,
    }
