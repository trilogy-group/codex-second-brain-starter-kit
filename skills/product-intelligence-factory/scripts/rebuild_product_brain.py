#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DATE = "2026-04-19"
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
ARTICLE_REF_RE = re.compile(r"\bArticle\s+(\d{4,6})\b", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
SUPPORT_ARTICLE_URL_RE = re.compile(r"/article/(\d{4,8})(?:[/?#].*)?$", re.IGNORECASE)
NOISE_RE = re.compile(
    r"^(pleasesign into comment|comments|posted|sign in|log in|login)$",
    re.IGNORECASE,
)

PRODUCT_CONTEXT = {"name": "Product", "slug": "product"}
STALE_DOC_HOSTS: set[str] = set()
CAPABILITIES: list[dict[str, Any]] = []
CAPABILITY_BY_KEY: dict[str, dict[str, Any]] = {}
CODE_EXTENSIONS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".rb",
    ".go",
    ".yml",
    ".yaml",
    ".json",
    ".swift",
    ".m",
    ".mm",
    ".h",
    ".sh",
    ".sql",
    ".py",
}
SPECIAL_CODE_FILES = {"Dockerfile", "Gemfile", "Podfile", "Fastfile", "Rakefile"}
IGNORED_DIRS = {".git", "node_modules", "Pods", "vendor", "dist", "build", "__pycache__"}
LOW_SIGNAL_CODE_TERMS = {
    ".gitlab-ci",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock",
    "jquery",
    "bootstrap",
    "react-16",
    "test-data",
    "fake-cards",
    "graphiql/rails",
}
TODO_RE = re.compile(r"\b(?:TODO|FIXME|XXX)\b", re.IGNORECASE)
CONSOLE_LOG_RE = re.compile(r"\b(?:console\.(?:log|debug|warn|error)|print)\s*\(")
SWALLOWED_ERROR_RE = re.compile(
    r"(?:catch\s*\([^)]*\)\s*\{[^{}]{0,240}return\s+(?:null|undefined|false|0|\"\"|''))|"
    r"(?:except\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*return\s+(?:None|False|0|\"\"|''))|"
    r"(?:rescue\s+[A-Za-z_:][A-Za-z0-9_:]*\s*;\s*nil)",
    re.IGNORECASE | re.DOTALL,
)
SHELL_EVAL_RE = re.compile(r"\beval\b")
RAW_HTML_RE = re.compile(r"\b(?:innerHTML\s*=|dangerouslySetInnerHTML)\b")
HTTP_SIGNAL_RE = re.compile(r"\b(?:fetch|axios|curl|http\.|https\.|Net::HTTP|requests\.)", re.IGNORECASE)
ENV_SIGNAL_RE = re.compile(r"\b(?:process\.env|ENV\[|os\.Getenv|System\.getenv)\b")
ASYNC_SIGNAL_RE = re.compile(r"\b(?:async|await|Promise<|Promise\.|go\s+[A-Za-z_]|dispatch_async)\b")
SQL_SIGNAL_RE = re.compile(r"\b(?:select|insert|update|delete|create\s+table|alter\s+table)\b", re.IGNORECASE)
UI_SIGNAL_RE = re.compile(r"\b(?:React|render\(|useState|useEffect|Component\b|UIViewController)\b")
CLASS_PATTERNS = (
    re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]*)\b"),
    re.compile(r"\btype\s+([A-Z][A-Za-z0-9_]*)\s+(?:struct|interface)\b"),
    re.compile(r"\binterface\s+([A-Z][A-Za-z0-9_]*)\b"),
    re.compile(r"@interface\s+([A-Z][A-Za-z0-9_]*)\b"),
)
FUNCTION_PATTERNS = (
    re.compile(r"\bexport\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\b(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\bfunc\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\bdef\s+([A-Za-z_][A-Za-z0-9_!?=]*)\s*\("),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_,\s]+)\s*=>"),
)
TYPE_ALIAS_PATTERNS = (
    re.compile(r"\btype\s+([A-Z][A-Za-z0-9_]*)\s*="),
    re.compile(r"\benum\s+([A-Z][A-Za-z0-9_]*)\b"),
)
SQL_OBJECT_RE = re.compile(r"\b(?:CREATE|ALTER)\s+(?:TABLE|VIEW|INDEX|FUNCTION|PROCEDURE)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)
COMMENT_PREFIXES = ("//", "#", "--", ";")
GENERIC_PATH_TERMS = {
    "src",
    "lib",
    "internal",
    "app",
    "apps",
    "services",
    "service",
    "components",
    "component",
    "modules",
    "module",
    "shared",
    "common",
    "utils",
    "utils",
    "devops",
    "domain",
    "api",
    "client",
    "server",
    "web",
    "mobile",
    "ios",
    "android",
    "config",
    "configs",
    "scripts",
    "test",
    "tests",
    "spec",
    "specs",
}
EXTERNAL_SYSTEM_TERMS = (
    "salesforce",
    "marketo",
    "hubspot",
    "eloqua",
    "tango",
    "oauth",
    "sso",
    "captcha",
    "redis",
    "postgres",
    "mysql",
    "metabase",
    "looker",
    "docker",
    "kubernetes",
    "fastlane",
    "referral",
)


def load_product_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    profile_path = manifest.get("profile", {}).get("intelligence_path")
    if not profile_path:
        raise SystemExit("Manifest must define profile.intelligence_path")
    path = Path(str(profile_path)).expanduser()
    data = yaml.safe_load(path.read_text()) or {}
    capabilities = data.get("capabilities") or []
    if not isinstance(capabilities, list):
        raise SystemExit(f"Profile capabilities must be a list: {path}")
    return {
        "path": path,
        "capabilities": capabilities,
    }


def configure_runtime(manifest: dict[str, Any], profile: dict[str, Any]) -> None:
    global PRODUCT_CONTEXT, STALE_DOC_HOSTS, CAPABILITIES, CAPABILITY_BY_KEY
    product = manifest.get("product") or {}
    PRODUCT_CONTEXT = {
        "name": str(product.get("name", "Product")),
        "slug": str(product.get("slug", "product")),
    }
    STALE_DOC_HOSTS = {
        str(host).lower()
        for host in (manifest.get("sources", {}).get("stale_doc_hosts") or [])
        if str(host).strip()
    }
    CAPABILITIES = list(profile["capabilities"])
    CAPABILITY_BY_KEY = {item["key"]: item for item in CAPABILITIES}


def repo_path_by_role(manifest: dict[str, Any], role: str) -> Path | None:
    for item in manifest.get("repositories", {}).get("items", []):
        if item.get("role") == role and item.get("local_path"):
            return Path(str(item["local_path"])).expanduser()
    return None


@dataclass
class Paths:
    vault: Path
    corpus: Path
    mirror: Path
    repos_root: Path
    json_dir: Path


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"Manifest root must be a mapping: {path}")
    return data


def manifest_paths(manifest: dict[str, Any]) -> Paths:
    product = manifest["product"]
    sources = manifest["sources"]
    repos = manifest["repositories"]
    mirror = Path(str(sources["mirror_path"])).expanduser()
    return Paths(
        vault=Path(str(product["vault_path"])).expanduser(),
        corpus=Path(str(sources["corpus_path"])).expanduser(),
        mirror=mirror,
        repos_root=Path(str(repos["local_clone_root"])).expanduser(),
        json_dir=mirror / "inventories",
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def slugify(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", " ", value).strip()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def dedupe_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def clean_display_title(value: str) -> str:
    value = normalize_text(value.replace("`", "'").replace("|", " "))
    if re.fullmatch(r"\d+-[a-z0-9-]+", value.lower()):
        value = value.split("-", 1)[1].replace("-", " ").title()
    return value[:160] or "Untitled"


def safe_filename(value: str, limit: int = 120) -> str:
    value = re.sub(r"[^A-Za-z0-9 ._-]+", "", value).strip()
    return value[:limit].rstrip(" .") or "Untitled"


def title_from_text(text: str, fallback: str) -> str:
    match = HEADING_RE.search(text)
    if match:
        return clean_display_title(match.group(2))
    for line in text.splitlines():
        line = normalize_text(line)
        if line:
            return clean_display_title(line)
    return clean_display_title(fallback)


def is_noise(line: str) -> bool:
    line = normalize_text(line)
    if not line:
        return True
    if NOISE_RE.match(line):
        return True
    if line.lower().startswith("*source:*"):
        return True
    return False


def unique_lines(lines: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        norm = dedupe_key(line)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        result.append(normalize_text(line))
        if len(result) >= limit:
            break
    return result


def text_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9]{3,}", value.lower())}


def note_code_search_keywords(signals: dict[str, Any], capabilities: list[str]) -> list[str]:
    phrases: list[str] = [signals["title"]]
    phrases.extend(signals["headings"][:6])
    phrases.extend(signals["bullets"][:4])
    phrases.extend(paragraph[:80] for paragraph in signals["paragraphs"][:2])
    for capability_key in capabilities:
        capability = CAPABILITY_BY_KEY[capability_key]
        phrases.append(capability["title"])
        phrases.extend(capability["keywords"][:6])
    return unique_lines([phrase for phrase in phrases if len(normalize_text(phrase)) > 2], 16)


def rank_code_hits_for_keywords(
    hits: list[dict[str, Any]],
    keywords: list[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    keyword_tokens = set()
    for keyword in keywords:
        keyword_tokens.update(text_tokens(keyword))
    if not keyword_tokens:
        return hits[:limit]

    ranked: list[tuple[int, dict[str, Any]]] = []
    for hit in hits:
        haystack = " ".join(
            [
                hit.get("relative_path", ""),
                hit.get("sample", ""),
                hit.get("repo", ""),
            ]
        )
        score = hit.get("score", 0)
        score += len(keyword_tokens.intersection(text_tokens(haystack)))
        if is_low_signal_code_hit(hit):
            score -= 4
        ranked.append((score, hit))
    ranked.sort(key=lambda item: (-item[0], item[1].get("relative_path", "")))
    return prune_code_hits([hit for _, hit in ranked], limit)


def is_low_signal_code_hit(hit: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(hit.get("repo", "")),
            str(hit.get("relative_path", "")),
            str(hit.get("sample", "")),
        ]
    ).lower()
    return any(term in haystack for term in LOW_SIGNAL_CODE_TERMS)


def prune_code_hits(hits: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    preferred = [hit for hit in hits if not is_low_signal_code_hit(hit)]
    fallback = [hit for hit in hits if is_low_signal_code_hit(hit)]
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for hit in [*preferred, *fallback]:
        key = (hit.get("repo", ""), hit.get("relative_path", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
        if len(deduped) >= limit:
            break
    return deduped


def note_code_hits(
    repo_roots: dict[str, Path],
    repo_names: list[str],
    signals: dict[str, Any],
    capabilities: list[str],
    capability_code_hits: dict[str, list[dict[str, Any]]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    del repo_roots
    del repo_names
    keywords = note_code_search_keywords(signals, capabilities)
    fallback_hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for capability_key in capabilities:
        for hit in capability_code_hits.get(capability_key, []):
            key = (hit.get("repo", ""), hit.get("relative_path", ""))
            if key in seen:
                continue
            seen.add(key)
            fallback_hits.append(hit)
    return rank_code_hits_for_keywords(fallback_hits, keywords, limit=limit)


def support_article_id_from_url(url: str) -> str | None:
    match = SUPPORT_ARTICLE_URL_RE.search(url)
    if not match:
        return None
    return match.group(1)


def clean_imported_markdown(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    if "\n---\n" in normalized:
        head, tail = normalized.split("\n---\n", 1)
        if "*Source:*" in head:
            normalized = tail

    cleaned_lines: list[str] = []
    previous_blank = True
    for raw_line in normalized.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("*Source:*"):
            continue
        if is_noise(stripped):
            continue
        if not stripped:
            if previous_blank:
                continue
            cleaned_lines.append("")
            previous_blank = True
            continue
        cleaned_lines.append(line)
        previous_blank = False
    return "\n".join(cleaned_lines).strip()


def resolve_wiki_target(target: str, current_relative_path: str | None) -> str | None:
    candidate = target.strip()
    if not candidate or "://" in candidate:
        return None
    candidate = candidate.split("#", 1)[0].split("?", 1)[0]
    if not candidate.endswith(".md"):
        return None
    base = Path(current_relative_path).parent if current_relative_path else Path(".")
    return (base / candidate).as_posix()


def obsidianize_markdown(
    text: str,
    *,
    article_note_stems: dict[str, str],
    wiki_note_stems: dict[str, str],
    current_relative_path: str | None = None,
) -> str:
    cleaned = clean_imported_markdown(text)

    def replace_markdown_link(match: re.Match[str]) -> str:
        label = normalize_text(match.group(1))
        target = match.group(2).strip()
        article_id = support_article_id_from_url(target)
        if article_id and article_id in article_note_stems:
            return f"[[{article_note_stems[article_id]}|{label or f'Article {article_id}'}]]"
        wiki_target = resolve_wiki_target(target, current_relative_path)
        if wiki_target and wiki_target in wiki_note_stems:
            return f"[[{wiki_note_stems[wiki_target]}|{label or Path(wiki_target).stem}]]"
        return match.group(0)

    transformed = MARKDOWN_LINK_RE.sub(replace_markdown_link, cleaned)

    def replace_article_ref(match: re.Match[str]) -> str:
        article_id = match.group(1)
        stem = article_note_stems.get(article_id)
        if not stem:
            return match.group(0)
        return f"[[{stem}|Article {article_id}]]"

    transformed = ARTICLE_REF_RE.sub(replace_article_ref, transformed)
    return transformed


def extract_signals(text: str, fallback_title: str) -> dict[str, Any]:
    title = title_from_text(text, fallback_title)
    headings = unique_lines([match.group(2) for match in HEADING_RE.finditer(text)], 12)
    bullets: list[str] = []
    paragraphs: list[str] = []
    urls = sorted({item.rstrip(".,;:)]}`\"'") for item in URL_RE.findall(text)})
    article_refs = sorted(set(ARTICLE_REF_RE.findall(text)))

    for raw in text.splitlines():
        line = normalize_text(raw)
        if is_noise(line) or line == "---":
            continue
        if line.startswith("#"):
            continue
        if line.startswith("- "):
            candidate = normalize_text(line[2:])
            if candidate and len(candidate) > 8:
                bullets.append(candidate)
            continue
        if len(line) > 30:
            paragraphs.append(line)

    return {
        "title": title,
        "headings": headings,
        "bullets": unique_lines(bullets, 12),
        "paragraphs": unique_lines(paragraphs, 8),
        "urls": urls[:15],
        "article_refs": article_refs,
    }


def classify_capabilities(title: str, text: str, hints: str = "") -> list[str]:
    haystack = f"{title}\n{text}\n{hints}".lower()
    title_lower = title.lower()
    scored: list[tuple[int, str]] = []
    for capability in CAPABILITIES:
        score = 0
        for keyword in capability["keywords"]:
            key = keyword.lower()
            if key in title_lower:
                score += 3
            elif key in haystack:
                score += 1
        if score > 0:
            scored.append((score, capability["key"]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    keys = [key for _, key in scored[:3]]
    if not keys:
        return ["platform-core"]
    return keys


def yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    return json.dumps(str(value))


def frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def note_link(stem: str) -> str:
    return f"[[{stem}]]"


def source_link_summary(link_records: list[dict[str, Any]]) -> tuple[dict[str, int], list[tuple[str, int]]]:
    counts = Counter(record["status"] for record in link_records)
    domains = Counter(record["domain"] for record in link_records)
    return dict(counts), domains.most_common(8)


def uncaptured_link_records(link_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked_statuses = {
        "blocked",
        "auth-gated",
        "likely-auth-gated",
        "needs-google-drive",
        "binary-or-empty",
    }
    return [record for record in link_records if record.get("status") in blocked_statuses and record.get("url")]


def format_uncaptured_link(record: dict[str, Any]) -> str:
    details: list[str] = []
    if record.get("http_status"):
        details.append(f"http `{record['http_status']}`")
    if record.get("error"):
        details.append(f"error `{normalize_text(str(record['error']))[:160]}`")
    if record.get("source_refs"):
        refs = ", ".join(f"`{ref}`" for ref in record["source_refs"][:3])
        details.append(f"sources: {refs}")
    suffix = f" | {'; '.join(details)}" if details else ""
    return f"[{record['status']}] [{record['url']}]({record['url']}){suffix}"


def expected_repo_names(capabilities: list[str]) -> list[str]:
    repo_names = [
        repo_name
        for capability_key in capabilities
        for repo_name in CAPABILITY_BY_KEY[capability_key]["repos"]
    ]
    return unique_lines(repo_names, 20)


def detect_note_conflicts(
    *,
    text: str,
    link_records: list[dict[str, Any]],
    code_hits: list[dict[str, Any]],
    repo_names: list[str],
) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    status_counts = Counter(record.get("status") for record in link_records)
    stale_doc_count = status_counts.get("stale-doc-reference", 0)
    blocked_count = status_counts.get("blocked", 0)
    drive_count = status_counts.get("needs-google-drive", 0)

    if stale_doc_count:
        conflicts.append(
            {
                "kind": "documentation-drift",
                "message": f"Documentation drift: this note still points to `{stale_doc_count}` legacy documentation link(s) on stale hosts even though GitHub is the declared code source of truth.",
            }
        )

    if blocked_count or drive_count:
        gap_parts: list[str] = []
        if blocked_count:
            gap_parts.append(f"`{blocked_count}` blocked external link(s)")
        if drive_count:
            gap_parts.append(f"`{drive_count}` Google Drive source(s) that still need authenticated capture")
        conflicts.append(
            {
                "kind": "restricted-source",
                "message": f"Access gap: this note depends on {' and '.join(gap_parts)}. See `## Uncaptured evidence` below for the exact URLs.",
            }
        )

    if repo_names and not code_hits:
        conflicts.append(
            {
                "kind": "code-traceability-gap",
                "message": f"Code traceability gap: no direct code reference was found in the expected repositories ({', '.join(f'`{name}`' for name in repo_names)}), so this topic is not yet anchored to an implementation path.",
            }
        )

    if "gitlab" in text.lower() and not stale_doc_count:
        conflicts.append(
            {
                "kind": "documentation-drift",
                "message": "Documentation drift: the source text still mentions legacy GitLab locations even though GitHub is the declared code source of truth.",
            }
        )
    return conflicts


def code_reference_link(hit: dict[str, Any], code_reference_stems: dict[tuple[str, str], str]) -> str:
    stem = code_reference_stems[(hit["repo"], hit["relative_path"])]
    label = f"{hit['repo']}/{hit['relative_path']}"
    if hit.get("line_number"):
        label = f"{label}:{hit['line_number']}"
    if hit.get("sample"):
        return f"[[{stem}|{label}]] :: {hit['sample']}"
    return f"[[{stem}|{label}]]"


def stem_for_support(article: dict[str, Any], display_title: str) -> str:
    article_id = article.get("article_id") or ""
    prefix = "Support" if article_id else "Support Reference"
    identity = article_id or Path(article["relative_path"]).stem.split("-", 1)[0]
    return safe_filename(f"{prefix} - {identity} - {display_title}")


def stem_for_wiki(relative_path: str, display_title: str) -> str:
    section = Path(relative_path).parts[0] if len(Path(relative_path).parts) > 1 else "Root"
    path_hint = safe_filename(Path(relative_path).stem.replace("-", " "), limit=48)
    suffix = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:8]
    if path_hint and dedupe_key(path_hint) != dedupe_key(display_title):
        return safe_filename(f"Wiki - {section} - {display_title} - {path_hint} - {suffix}", limit=180)
    return safe_filename(f"Wiki - {section} - {display_title} - {suffix}", limit=180)


def stem_for_repo(name: str) -> str:
    return safe_filename(f"Repo - {name}")


def stem_for_capability(title: str) -> str:
    return safe_filename(f"Capability - {title}")


def stem_for_code_reference(repo_name: str, relative_path: str) -> str:
    flattened_path = relative_path.replace("/", " -- ")
    return safe_filename(f"Code Ref - {repo_name} - {flattened_path}", limit=180)


def repo_lookup(manifest: dict[str, Any]) -> dict[str, Path]:
    return {
        item["name"]: Path(str(item["local_path"])).expanduser()
        for item in manifest["repositories"]["items"]
    }


def is_code_like(path: Path) -> bool:
    if path.name in SPECIAL_CODE_FILES:
        return True
    if path.suffix.lower() in CODE_EXTENSIONS:
        return True
    return False


def representative_files(repo_path: Path, limit: int = 14) -> list[Path]:
    preferred = [
        "README.md",
        "package.json",
        "Dockerfile",
        "Gemfile",
        "Podfile",
        "docker-compose.local-platform.yml",
        "docker-compose.yml",
        "app.js",
        "fastlane/Fastfile",
    ]
    results: list[Path] = []
    seen: set[str] = set()
    for relative in preferred:
        candidate = repo_path / relative
        if candidate.exists():
            results.append(candidate)
            seen.add(candidate.as_posix())
    for path in repo_path.rglob("*"):
        if len(path.relative_to(repo_path).parts) > 4:
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if not path.is_file() or not is_code_like(path):
            continue
        if path.as_posix() in seen:
            continue
        results.append(path)
        seen.add(path.as_posix())
        if len(results) >= limit:
            break
    return results[:limit]


def rg_code_hits(repo_roots: dict[str, Path], repo_names: list[str], keywords: list[str], limit: int = 12) -> list[dict[str, Any]]:
    if shutil.which("rg") is None:
        return []
    search_paths = [repo_roots[name] for name in repo_names if name in repo_roots and repo_roots[name].exists()]
    if not search_paths:
        return []
    pattern = "|".join(re.escape(keyword) for keyword in keywords if len(keyword) > 2)
    if not pattern:
        return []

    cmd = [
        "rg",
        "-n",
        "-i",
        "-m",
        "3",
        "--hidden",
        "--glob",
        "!**/.git/**",
        "--glob",
        "!**/node_modules/**",
        "--glob",
        "!**/Pods/**",
        "--glob",
        "!**/vendor/**",
        "--glob",
        "!**/dist/**",
        "--glob",
        "!**/build/**",
        pattern,
        *[str(path) for path in search_paths],
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode not in {0, 1}:
        return []

    file_scores: Counter[str] = Counter()
    first_match: dict[str, str] = {}
    first_line_number: dict[str, int] = {}
    repo_by_file: dict[str, str] = {}
    for raw in completed.stdout.splitlines():
        parts = raw.split(":", 2)
        if len(parts) < 3:
            continue
        file_path = Path(parts[0])
        try:
            line_number = int(parts[1])
        except ValueError:
            line_number = 0
        if not file_path.exists() or not is_code_like(file_path):
            continue
        if any(part in IGNORED_DIRS for part in file_path.parts):
            continue
        file_scores[str(file_path)] += 1
        first_match.setdefault(str(file_path), normalize_text(parts[2])[:180])
        first_line_number.setdefault(str(file_path), line_number)
        for repo_name, repo_root in repo_roots.items():
            try:
                file_path.relative_to(repo_root)
                repo_by_file[str(file_path)] = repo_name
                break
            except ValueError:
                continue

    ranked = sorted(file_scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
    hits: list[dict[str, Any]] = []
    for file_path, score in ranked:
        repo_name = repo_by_file.get(file_path, "")
        repo_root = repo_roots.get(repo_name)
        relative = Path(file_path).relative_to(repo_root).as_posix() if repo_root else Path(file_path).name
        hits.append(
            {
                "repo": repo_name,
                "absolute_path": file_path,
                "relative_path": relative,
                "line_number": first_line_number.get(file_path, 0),
                "score": score,
                "sample": first_match.get(file_path, ""),
            }
        )
    return hits


def write_note(path: Path, body: str) -> None:
    ensure_dir(path.parent)
    path.write_text(body.rstrip() + "\n")


def clear_markdown_dir(path: Path) -> None:
    if not path.exists():
        ensure_dir(path)
        return
    for file_path in sorted(path.rglob("*.md"), reverse=True):
        file_path.unlink()
    for directory in sorted((item for item in path.rglob("*") if item.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()


def sanitize_vault_notes(vault_path: Path) -> dict[str, int]:
    module_path = Path(__file__).with_name("sanitize_vault_privacy.py")
    spec = importlib.util.spec_from_file_location("sanitize_vault_privacy_runtime", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.sanitize_vault_markdown(vault_path)


@dataclass
class CodeReferenceAnalysis:
    artifact_kind: str
    language: str
    classes: list[str]
    functions: list[str]
    types: list[str]
    comments: list[str]
    implementation_signals: list[str]
    intentions: list[str]
    risks: list[str]
    conflicts: list[str]


def infer_code_language(relative_path: str) -> str:
    path = Path(relative_path)
    name = path.name
    suffix = path.suffix.lower()
    if name == "Dockerfile":
        return "Dockerfile"
    if name in {"Gemfile", "Podfile", "Fastfile", "Rakefile"}:
        return "Ruby DSL"
    return {
        ".js": "JavaScript",
        ".jsx": "JSX",
        ".ts": "TypeScript",
        ".tsx": "TSX",
        ".rb": "Ruby",
        ".go": "Go",
        ".yml": "YAML",
        ".yaml": "YAML",
        ".json": "JSON",
        ".swift": "Swift",
        ".m": "Objective-C",
        ".mm": "Objective-C++",
        ".h": "C/Objective-C header",
        ".sh": "Shell",
        ".sql": "SQL",
        ".py": "Python",
    }.get(suffix, "Code")


def infer_artifact_kind(relative_path: str, text: str) -> str:
    lower_path = relative_path.lower()
    suffix = Path(relative_path).suffix.lower()
    name = Path(relative_path).name
    if name == "Dockerfile":
        return "Container build definition"
    if "docker-compose" in lower_path:
        return "Container orchestration config"
    if ".gitlab-ci" in lower_path or ".github/workflows/" in lower_path:
        return "CI/CD pipeline config"
    if lower_path.endswith((".test.js", ".test.jsx", ".test.ts", ".test.tsx", ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx", "_test.go", "_spec.rb")):
        return "Automated test suite"
    if "package-lock.json" in lower_path or "yarn.lock" in lower_path or "pnpm-lock" in lower_path:
        return "Dependency lockfile"
    if suffix == ".sql":
        return "SQL script"
    if suffix in {".yml", ".yaml"}:
        return "YAML configuration"
    if suffix == ".json":
        return "JSON configuration or schema"
    if suffix in {".jsx", ".tsx"}:
        return "Frontend component module"
    if suffix in {".js", ".ts"}:
        if any(term in lower_path for term in ("component", "view", "container", "page")) or UI_SIGNAL_RE.search(text):
            return "Frontend or UI module"
        if any(term in lower_path for term in ("service", "api", "integration", "connector", "gateway", "auth")):
            return "Service or integration module"
        return "Application module"
    if suffix == ".go":
        return "Go package or service"
    if suffix == ".rb":
        return "Ruby class or service"
    if suffix == ".swift":
        return "iOS source file"
    if suffix in {".m", ".mm", ".h"}:
        return "Objective-C source file"
    if suffix == ".sh":
        return "Shell automation script"
    if suffix == ".py":
        return "Python module"
    return "Code artifact"


def split_identifier_words(value: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value.replace("_", " ").replace("-", " "))
    return normalize_text(spaced).lower()


def read_code_reference_text(path: Path, max_chars: int = 32000) -> str:
    text = path.read_text(errors="ignore")
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def extract_top_comment_lines(text: str, limit: int = 4) -> list[str]:
    lines: list[str] = []
    in_block = False
    for raw in text.splitlines()[:80]:
        stripped = raw.strip()
        if not stripped and not lines:
            continue
        if stripped.startswith("#!"):
            continue
        if stripped.startswith("/*"):
            in_block = True
            stripped = stripped[2:]
        if in_block:
            if "*/" in stripped:
                stripped, _ = stripped.split("*/", 1)
                in_block = False
            stripped = stripped.lstrip("*").strip()
            if stripped:
                lines.append(normalize_text(stripped))
            if len(lines) >= limit:
                break
            continue
        if any(stripped.startswith(prefix) for prefix in COMMENT_PREFIXES):
            candidate = stripped[2:] if stripped.startswith(("//", "--")) else stripped[1:]
            candidate = normalize_text(candidate)
            if candidate:
                lines.append(candidate)
            if len(lines) >= limit:
                break
            continue
        if lines:
            break
        if stripped:
            break
    return unique_lines(lines, limit)


def extract_code_symbols(text: str) -> dict[str, list[str]]:
    classes: list[str] = []
    functions: list[str] = []
    types: list[str] = []
    for pattern in CLASS_PATTERNS:
        classes.extend(match.group(1) for match in pattern.finditer(text))
    for pattern in FUNCTION_PATTERNS:
        functions.extend(match.group(1) for match in pattern.finditer(text))
    for pattern in TYPE_ALIAS_PATTERNS:
        types.extend(match.group(1) for match in pattern.finditer(text))
    types.extend(match.group(1) for match in SQL_OBJECT_RE.finditer(text))
    return {
        "classes": unique_lines(classes, 8),
        "functions": unique_lines(functions, 10),
        "types": unique_lines(types, 8),
    }


def summarize_path_focus(relative_path: str) -> str:
    parts = []
    for part in Path(relative_path).parts:
        token = dedupe_key(part)
        if not token or token in GENERIC_PATH_TERMS:
            continue
        clean = split_identifier_words(Path(part).stem)
        if clean:
            parts.append(clean)
    return ", ".join(unique_lines(parts, 5))


def detect_external_systems(text: str, relative_path: str) -> list[str]:
    haystack = f"{relative_path}\n{text}".lower()
    return unique_lines([term.title() for term in EXTERNAL_SYSTEM_TERMS if term in haystack], 6)


def detect_code_risks(text: str, relative_path: str) -> list[str]:
    risks: list[str] = []
    if TODO_RE.search(text):
        risks.append("TODO/FIXME marker present, which suggests unfinished behavior, cleanup debt, or known instability.")
    if CONSOLE_LOG_RE.search(text):
        risks.append("Debug or console logging is present; verify that noisy runtime output or sensitive data is not emitted in production paths.")
    if SWALLOWED_ERROR_RE.search(text):
        risks.append("The error handling pattern may swallow failures by returning a fallback value from a catch/rescue path instead of surfacing the underlying issue.")
    if "gitlab" in relative_path.lower():
        risks.append("This file sits on a legacy GitLab-oriented path, so operational assumptions around CI/CD or source-of-truth may be outdated.")
    if RAW_HTML_RE.search(text):
        risks.append("Raw HTML rendering is present; this deserves a security review for XSS or unsafe content handling.")
    if SHELL_EVAL_RE.search(text):
        risks.append("Dynamic shell evaluation is present; verify the evaluated input is trusted and that runtime behavior is deterministic.")
    if re.search(r"http://", text, re.IGNORECASE):
        risks.append("A plain HTTP endpoint is referenced; verify transport security and environment suitability.")
    return unique_lines(risks, 8)


def detect_code_conflicts(text: str, relative_path: str, artifact_kind: str) -> list[str]:
    conflicts: list[str] = []
    lower_path = relative_path.lower()
    if "gitlab" in lower_path:
        conflicts.append("This reference targets a legacy GitLab or GitLab CI surface, so it may be historical or drift-prone relative to the current GitHub-centered engineering workflow.")
    if any(host in text.lower() for host in STALE_DOC_HOSTS):
        conflicts.append("A stale internal documentation host is referenced from this code artifact, which may point readers toward outdated operational context.")
    if artifact_kind == "Dependency lockfile":
        conflicts.append("This note points to a dependency lockfile, which is supporting evidence rather than primary implementation logic.")
    return unique_lines(conflicts, 6)


def detect_implementation_signals(text: str, relative_path: str, artifact_kind: str, symbols: dict[str, list[str]]) -> list[str]:
    signals = [f"Artifact kind: {artifact_kind}."]
    if symbols["classes"]:
        signals.append(f"Primary classes or structs: {', '.join(f'`{name}`' for name in symbols['classes'][:5])}.")
    if symbols["functions"]:
        signals.append(f"Primary functions or entry points: {', '.join(f'`{name}`' for name in symbols['functions'][:6])}.")
    if symbols["types"]:
        signals.append(f"Supporting types or schema objects: {', '.join(f'`{name}`' for name in symbols['types'][:5])}.")
    if HTTP_SIGNAL_RE.search(text):
        signals.append("Operational signal: network or HTTP behavior appears in this file.")
    if ENV_SIGNAL_RE.search(text):
        signals.append("Operational signal: environment-based configuration is used here.")
    if ASYNC_SIGNAL_RE.search(text):
        signals.append("Operational signal: asynchronous execution is part of the implementation path.")
    if SQL_SIGNAL_RE.search(text) or Path(relative_path).suffix.lower() == ".sql":
        signals.append("Operational signal: database or SQL behavior is present.")
    if UI_SIGNAL_RE.search(text):
        signals.append("Operational signal: this file participates in UI rendering or component composition.")
    external_systems = detect_external_systems(text, relative_path)
    if external_systems:
        signals.append(f"External systems or product surfaces detected: {', '.join(f'`{name}`' for name in external_systems)}.")
    return unique_lines(signals, 10)


def infer_intentions(hit: dict[str, Any], artifact_kind: str, text: str, symbols: dict[str, list[str]], comments: list[str]) -> list[str]:
    intentions: list[str] = []
    if comments:
        intentions.extend(comments[:2])
    path_focus = summarize_path_focus(hit["relative_path"])
    if path_focus:
        intentions.append(f"The path suggests this {artifact_kind.lower()} is focused on {path_focus}.")
    symbol_focus = unique_lines(
        [split_identifier_words(name) for name in [*symbols["classes"], *symbols["functions"], *symbols["types"]]],
        5,
    )
    if symbol_focus:
        intentions.append(f"Named symbols indicate responsibilities around {', '.join(symbol_focus)}.")
    if hit.get("sample"):
        intentions.append(f"Representative match focus: `{normalize_text(str(hit['sample']))[:180]}`.")
    if not intentions:
        intentions.append(f"This {artifact_kind.lower()} was selected as a likely implementation anchor based on code-search relevance and repository context.")
    return unique_lines(intentions, 6)


def analyze_code_reference(hit: dict[str, Any]) -> CodeReferenceAnalysis:
    path = Path(str(hit["absolute_path"]))
    text = read_code_reference_text(path)
    artifact_kind = infer_artifact_kind(hit["relative_path"], text)
    symbols = extract_code_symbols(text)
    comments = extract_top_comment_lines(text)
    return CodeReferenceAnalysis(
        artifact_kind=artifact_kind,
        language=infer_code_language(hit["relative_path"]),
        classes=symbols["classes"],
        functions=symbols["functions"],
        types=symbols["types"],
        comments=comments,
        implementation_signals=detect_implementation_signals(text, hit["relative_path"], artifact_kind, symbols),
        intentions=infer_intentions(hit, artifact_kind, text, symbols, comments),
        risks=detect_code_risks(text, hit["relative_path"]),
        conflicts=detect_code_conflicts(text, hit["relative_path"], artifact_kind),
    )


def build_support_note(
    item: dict[str, Any],
    raw_path: Path,
    stem: str,
    capabilities: list[str],
    repo_links: list[str],
    link_records: list[dict[str, Any]],
    article_note_stems: dict[str, str],
    wiki_note_stems: dict[str, str],
    related_support_links: list[str],
    related_wiki_links: list[str],
    code_reference_links: list[str],
    conflicts: list[str],
) -> str:
    text = raw_path.read_text(errors="ignore")
    signals = extract_signals(text, item["title"])
    status_counts, domains = source_link_summary(link_records)
    uncaptured_links = uncaptured_link_records(link_records)
    display_title = signals["title"]
    related_articles = [
        note_link(article_note_stems[article_id])
        for article_id in signals["article_refs"]
        if article_id in article_note_stems and article_note_stems[article_id] != stem
    ][:20]
    related_caps = [note_link(stem_for_capability(CAPABILITY_BY_KEY[key]["title"])) for key in capabilities]
    content_markdown = obsidianize_markdown(
        text,
        article_note_stems=article_note_stems,
        wiki_note_stems=wiki_note_stems,
    )
    resource_links = [
        f"- [{record['url']}]({record['url']})"
        for record in link_records
        if record.get("url") and record.get("status") == "mirrored"
    ][:15]
    support_relationships = unique_lines([*related_articles, *related_support_links], 16)

    lines = [
        frontmatter(
            {
                "type": "concept",
                "area": PRODUCT_CONTEXT["slug"],
                "source": "support-export",
                "source_path": str(raw_path),
                "source_url": item.get("source_url") or "",
                "article_id": item.get("article_id") or "",
                "tags": ["support", item["category"], *capabilities],
            }
        ),
        f"# {display_title}",
        "",
        f"- Raw source: `{raw_path}`",
        f"- Source URL: {item.get('source_url') or '(local-only)'}",
        f"- Relative corpus path: `{item['relative_path']}`",
        f"- Linked page statuses: `{status_counts or {'none': 0}}`",
        "",
        "## Summary",
        "",
    ]
    summary = signals["paragraphs"][0] if signals["paragraphs"] else f"This source was ingested from the {PRODUCT_CONTEXT['name']} support corpus."
    lines.append(summary)

    if signals["headings"]:
        lines.extend(["", "## Key sections", ""])
        lines.extend(f"- {heading}" for heading in signals["headings"][:8])

    if signals["bullets"]:
        lines.extend(["", "## Key evidence", ""])
        lines.extend(f"- {bullet}" for bullet in signals["bullets"][:10])

    if domains:
        lines.extend(["", "## Linked domains", ""])
        lines.extend(f"- {domain}: `{count}`" for domain, count in domains[:6])

    if support_relationships:
        lines.extend(["", "## Related support notes", ""])
        lines.extend(f"- {link}" for link in support_relationships)

    if related_wiki_links:
        lines.extend(["", "## Related wiki notes", ""])
        lines.extend(f"- {link}" for link in related_wiki_links[:16])

    lines.extend(["", "## Related capabilities", ""])
    lines.extend(f"- {link}" for link in related_caps)

    lines.extend(["", "## Source code references", ""])
    if code_reference_links:
        lines.extend(f"- {link}" for link in code_reference_links)
    else:
        lines.append("- No direct code reference was found for this note yet.")

    lines.extend(["", "## Related code and repo notes", ""])
    lines.extend(f"- {link}" for link in repo_links)

    lines.extend(["", "## Conflicts and mismatches", ""])
    if conflicts:
        lines.extend(f"- {conflict}" for conflict in conflicts)
    else:
        lines.append("- No clear mismatch was detected from the accessible sources and code references.")

    if uncaptured_links:
        lines.extend(["", "## Uncaptured evidence", ""])
        lines.extend(f"- {format_uncaptured_link(record)}" for record in uncaptured_links)

    if resource_links:
        lines.extend(["", "## Linked resources", ""])
        lines.extend(resource_links)

    if content_markdown:
        lines.extend(["", "## Full Article Content", "", content_markdown])

    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[Support Article Index]]",
            "- [[Support Articles Hub]]",
            "- [[Product Capability Map]]",
        ]
    )
    return "\n".join(lines)


def build_wiki_note(
    relative_path: str,
    raw_path: Path,
    stem: str,
    capabilities: list[str],
    repo_links: list[str],
    link_records: list[dict[str, Any]],
    article_note_stems: dict[str, str],
    wiki_note_stems: dict[str, str],
    related_support_links: list[str],
    related_wiki_links: list[str],
    code_reference_links: list[str],
    conflicts: list[str],
) -> str:
    text = raw_path.read_text(errors="ignore")
    signals = extract_signals(text, raw_path.stem)
    status_counts, domains = source_link_summary(link_records)
    uncaptured_links = uncaptured_link_records(link_records)
    related_caps = [note_link(stem_for_capability(CAPABILITY_BY_KEY[key]["title"])) for key in capabilities]
    content_markdown = obsidianize_markdown(
        text,
        article_note_stems=article_note_stems,
        wiki_note_stems=wiki_note_stems,
        current_relative_path=relative_path,
    )
    resource_links = [
        f"- [{record['url']}]({record['url']})"
        for record in link_records
        if record.get("url") and record.get("status") == "mirrored"
    ][:15]

    lines = [
        frontmatter(
            {
                "type": "concept",
                "area": PRODUCT_CONTEXT["slug"],
                "source": "engineering-wiki",
                "source_path": str(raw_path),
                "section": Path(relative_path).parts[0] if len(Path(relative_path).parts) > 1 else "root",
                "tags": ["wiki", *capabilities],
            }
        ),
        f"# {signals['title']}",
        "",
        f"- Raw wiki path: `{raw_path}`",
        f"- Relative wiki path: `{relative_path}`",
        f"- Linked page statuses: `{status_counts or {'none': 0}}`",
        "",
        "## Summary",
        "",
    ]
    summary = signals["paragraphs"][0] if signals["paragraphs"] else f"This page was ingested from the {PRODUCT_CONTEXT['name']} engineering wiki."
    lines.append(summary)

    if signals["headings"]:
        lines.extend(["", "## Key sections", ""])
        lines.extend(f"- {heading}" for heading in signals["headings"][:10])

    if signals["bullets"]:
        lines.extend(["", "## Key evidence", ""])
        lines.extend(f"- {bullet}" for bullet in signals["bullets"][:10])

    if domains:
        lines.extend(["", "## Linked domains", ""])
        lines.extend(f"- {domain}: `{count}`" for domain, count in domains[:6])

    if related_support_links:
        lines.extend(["", "## Related support notes", ""])
        lines.extend(f"- {link}" for link in related_support_links[:16])

    if related_wiki_links:
        lines.extend(["", "## Related wiki notes", ""])
        lines.extend(f"- {link}" for link in related_wiki_links[:16])

    lines.extend(["", "## Related capabilities", ""])
    lines.extend(f"- {link}" for link in related_caps)

    lines.extend(["", "## Source code references", ""])
    if code_reference_links:
        lines.extend(f"- {link}" for link in code_reference_links)
    else:
        lines.append("- No direct code reference was found for this note yet.")

    lines.extend(["", "## Related code and repo notes", ""])
    lines.extend(f"- {link}" for link in repo_links)

    lines.extend(["", "## Conflicts and mismatches", ""])
    if conflicts:
        lines.extend(f"- {conflict}" for conflict in conflicts)
    else:
        lines.append("- No clear mismatch was detected from the accessible sources and code references.")

    if uncaptured_links:
        lines.extend(["", "## Uncaptured evidence", ""])
        lines.extend(f"- {format_uncaptured_link(record)}" for record in uncaptured_links)

    if resource_links:
        lines.extend(["", "## Linked resources", ""])
        lines.extend(resource_links)

    if content_markdown:
        lines.extend(["", "## Full Wiki Content", "", content_markdown])

    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[Engineering Wiki Index]]",
            "- [[Wiki Pages Hub]]",
            "- [[Product Capability Map]]",
        ]
    )
    return "\n".join(lines)


def build_repo_note(snapshot: dict[str, Any], repo_path: Path, capabilities: list[str]) -> str:
    stem = stem_for_repo(snapshot["name"])
    files = representative_files(repo_path)
    cap_links = [note_link(stem_for_capability(CAPABILITY_BY_KEY[key]["title"])) for key in capabilities]
    lines = [
        frontmatter(
            {
                "type": "concept",
                "area": PRODUCT_CONTEXT["slug"],
                "source": "repository-scan",
                "repo": snapshot["name"],
                "role": snapshot["role"],
                "branch": snapshot["branch"],
                "tags": ["repo", snapshot["role"]],
            }
        ),
        f"# {snapshot['name']}",
        "",
        f"- Role: `{snapshot['role']}`",
        f"- Branch: `{snapshot['branch']}`",
        f"- Local path: `{repo_path}`",
        f"- README title: {snapshot.get('readme_title') or '(missing)'}",
        f"- README summary: {snapshot.get('readme_summary') or '(missing)'}",
        "",
        "## Structure",
        "",
        f"- Top-level directories: {', '.join(f'`{name}`' for name in snapshot.get('top_dirs', [])[:12]) or '(none found)'}",
        f"- Key files: {', '.join(f'`{name}`' for name in snapshot.get('key_files', [])) or '(none found)'}",
    ]
    if snapshot.get("monorepo_apps"):
        lines.extend(["", "## Monorepo apps", ""])
        lines.extend(f"- `{name}`" for name in snapshot["monorepo_apps"][:20])
    if snapshot.get("monorepo_services"):
        lines.extend(["", "## Monorepo services", ""])
        lines.extend(f"- `{name}`" for name in snapshot["monorepo_services"][:25])
    if files:
        lines.extend(["", "## Representative code surfaces", ""])
        for file_path in files:
            relative = file_path.relative_to(repo_path).as_posix()
            lines.append(f"- `{relative}`")
    lines.extend(["", "## Related capabilities", ""])
    lines.extend(f"- {link}" for link in cap_links or ["[[Product Capability Map]]"])
    lines.extend(["", "## Related notes", "", "- [[Repo Catalog]]", "- [[Code Intelligence Hub]]", "- [[Architecture and Service Map]]"])
    return "\n".join(lines)


def build_code_reference_note(
    hit: dict[str, Any],
    support_links: list[str],
    wiki_links: list[str],
    capability_links: list[str],
) -> str:
    analysis = analyze_code_reference(hit)
    risk_count = len(analysis.risks)
    conflict_count = len(analysis.conflicts)
    lines = [
        frontmatter(
            {
                "type": "concept",
                "area": PRODUCT_CONTEXT["slug"],
                "source": "code-search",
                "repo": hit["repo"],
                "source_path": hit["absolute_path"],
                "language": analysis.language,
                "artifact_kind": analysis.artifact_kind,
                "risk_count": risk_count,
                "conflict_count": conflict_count,
                "tags": ["code-reference", hit["repo"]],
            }
        ),
        f"# {hit['repo']}/{hit['relative_path']}",
        "",
        f"- Repository note: {note_link(stem_for_repo(hit['repo']))}",
        f"- Relative path: `{hit['relative_path']}`",
        f"- Local path: `{hit['absolute_path']}`",
        f"- First matched line: `{hit.get('line_number') or 'n/a'}`",
    ]
    lines.extend(
        [
            "",
            "## Class and module summary",
            "",
            f"- Language: `{analysis.language}`",
            f"- Artifact kind: {analysis.artifact_kind}",
        ]
    )
    if analysis.classes:
        lines.append(f"- Classes or structs: {', '.join(f'`{name}`' for name in analysis.classes)}")
    if analysis.functions:
        lines.append(f"- Functions or entry points: {', '.join(f'`{name}`' for name in analysis.functions)}")
    if analysis.types:
        lines.append(f"- Types, interfaces, or schema objects: {', '.join(f'`{name}`' for name in analysis.types)}")
    if not any((analysis.classes, analysis.functions, analysis.types)):
        lines.append("- No named classes, functions, or schema objects were detected from the static scan.")

    lines.extend(["", "## Intentions and behavior", ""])
    lines.extend(f"- {item}" for item in analysis.intentions)

    if hit.get("sample"):
        lines.extend(["", "## Representative match", "", f"`{hit['sample']}`"])

    lines.extend(
        [
            "",
            "## Relevance",
            "",
            f"- Support notes: `{len(support_links)}`",
            f"- Wiki notes: `{len(wiki_links)}`",
            f"- Capability links: `{len(capability_links)}`",
            f"- Code-search score: `{hit.get('score', 0)}`",
            "- This note acts as an implementation anchor for the linked support, wiki, and capability evidence around the same topic.",
        ]
    )

    lines.extend(["", "## Implementation signals", ""])
    lines.extend(f"- {item}" for item in analysis.implementation_signals)

    lines.extend(["", "## Detected bugs and risks", ""])
    if analysis.risks:
        lines.extend(f"- {item}" for item in analysis.risks)
    else:
        lines.append("- No obvious static risk signals were detected from this code-reference summary pass.")

    lines.extend(["", "## Conflicts and mismatches", ""])
    if analysis.conflicts:
        lines.extend(f"- {item}" for item in analysis.conflicts)
    else:
        lines.append("- No direct mismatch or documentation-drift signals were detected for this code reference.")

    if capability_links:
        lines.extend(["", "## Related capabilities", ""])
        lines.extend(f"- {link}" for link in capability_links[:20])
    if support_links:
        lines.extend(["", "## Related support notes", ""])
        lines.extend(f"- {link}" for link in support_links[:30])
    if wiki_links:
        lines.extend(["", "## Related wiki notes", ""])
        lines.extend(f"- {link}" for link in wiki_links[:30])
    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[Code Reference Index]]",
            "- [[Code Intelligence Hub]]",
            "- [[Repo Catalog]]",
        ]
    )
    return "\n".join(lines)


def build_capability_note(
    capability: dict[str, Any],
    support_links: list[str],
    wiki_links: list[str],
    repo_note_links: list[str],
    code_hits: list[dict[str, Any]],
    code_reference_links: list[str],
    link_records: list[dict[str, Any]],
) -> str:
    status_counts = Counter(record["status"] for record in link_records)
    domain_counts = Counter(record["domain"] for record in link_records)
    lines = [
        frontmatter(
            {
                "type": "area",
                "area": PRODUCT_CONTEXT["slug"],
                "status": "active",
                "date": DATE,
                "source": "generated",
                "tags": ["capability", capability["key"]],
            }
        ),
        f"# {capability['title']}",
        "",
        capability["description"],
        "",
        "## Coverage snapshot",
        "",
        f"- Support notes: `{len(support_links)}`",
        f"- Wiki notes: `{len(wiki_links)}`",
        f"- Repo notes: `{len(repo_note_links)}`",
        f"- Code hits: `{len(code_hits)}`",
        f"- Linked pages by status: `{dict(status_counts) if status_counts else {'none': 0}}`",
    ]
    if domain_counts:
        lines.extend(["", "## Linked domains", ""])
        lines.extend(f"- {domain}: `{count}`" for domain, count in domain_counts.most_common(8))
    if repo_note_links:
        lines.extend(["", "## Primary repositories", ""])
        lines.extend(f"- {link}" for link in repo_note_links)
    lines.extend(["", "## Representative code paths", ""])
    if code_reference_links:
        lines.extend(f"- {link}" for link in code_reference_links[:20])
    elif code_hits:
        for hit in code_hits[:12]:
            lines.append(f"- `{hit['repo']}/{hit['relative_path']}`")
    else:
        lines.append("- No direct code references were generated for this capability yet.")
    if support_links:
        lines.extend(["", "## Representative support notes", ""])
        lines.extend(f"- {link}" for link in support_links[:20])
    if wiki_links:
        lines.extend(["", "## Representative wiki notes", ""])
        lines.extend(f"- {link}" for link in wiki_links[:20])
    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[Product Capability Map]]",
            "- [[Support-to-Code Map]]",
            "- [[Support Articles Hub]]",
            "- [[Wiki Pages Hub]]",
            "- [[Code Intelligence Hub]]",
        ]
    )
    return "\n".join(lines)


def build_support_articles_hub(grouped: dict[str, list[str]]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["support", "hub"]}),
        "# Support Articles Hub",
        "",
        "This hub links the ingested support corpus into durable article and reference notes.",
        "",
    ]
    for key in sorted(grouped):
        capability = CAPABILITY_BY_KEY[key]
        lines.append(f"## {capability['title']}")
        lines.append("")
        lines.append(f"- Capability note: {note_link(stem_for_capability(capability['title']))}")
        lines.extend(f"- {link}" for link in grouped[key][:40])
        if len(grouped[key]) > 40:
            lines.append(f"- ... `{len(grouped[key]) - 40}` more notes in this capability")
        lines.append("")
    lines.extend(["## Related notes", "", "- [[Support Article Index]]", "- [[Product Capability Map]]", "- [[Intelligence Home]]"])
    return "\n".join(lines)


def build_wiki_pages_hub(grouped: dict[str, list[str]]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["wiki", "hub"]}),
        "# Wiki Pages Hub",
        "",
        f"This hub links the local clone of the {PRODUCT_CONTEXT['name']} engineering wiki into durable notes.",
        "",
    ]
    for section in sorted(grouped):
        lines.append(f"## {section}")
        lines.append("")
        lines.extend(f"- {link}" for link in grouped[section])
        lines.append("")
    lines.extend(["## Related notes", "", "- [[Engineering Wiki Index]]", "- [[Product Capability Map]]", "- [[Intelligence Home]]"])
    return "\n".join(lines)


def build_code_intelligence_hub(repo_links: list[str], capability_links: list[str]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["code", "hub"]}),
        "# Code Intelligence Hub",
        "",
        "This hub connects repository scans and capability-level code evidence.",
        "",
        "## Repository notes",
        "",
    ]
    lines.extend(f"- {link}" for link in repo_links)
    lines.extend(["", "## Capability notes", ""])
    lines.extend(f"- {link}" for link in capability_links)
    lines.extend(["", "## Related notes", "", "- [[Code Reference Index]]", "- [[Repo Catalog]]", "- [[GitHub Source Of Truth]]", "- [[Support-to-Code Map]]", "- [[Conflict Log]]", "- [[Intelligence Home]]"])
    return "\n".join(lines)


def build_product_capability_map(capability_rows: list[dict[str, Any]]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["product", "capabilities"]}),
        "# Product Capability Map",
        "",
        "This note maps the support corpus, engineering wiki, and repositories into durable capability hubs.",
        "",
    ]
    for row in capability_rows:
        lines.append(f"## {row['title']}")
        lines.append("")
        lines.append(f"- Note: {row['link']}")
        lines.append(f"- Support notes: `{row['support_count']}`")
        lines.append(f"- Wiki notes: `{row['wiki_count']}`")
        lines.append(f"- Repositories: {', '.join(f'`{repo}`' for repo in row['repos'])}")
        lines.append(f"- Code hits: `{row['code_count']}`")
        lines.append("")
    lines.extend(["## Related notes", "", "- [[Support Articles Hub]]", "- [[Wiki Pages Hub]]", "- [[Code Intelligence Hub]]", "- [[Intelligence Home]]"])
    return "\n".join(lines)


def build_support_article_index(total_articles: int, total_refs: int, total_docx: int, grouped: dict[str, list[str]]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["sources", "support-index"]}),
        "# Support Article Index",
        "",
        f"- Support article notes: `{total_articles}`",
        f"- Reference document notes: `{total_refs}`",
        f"- DOCX extracts preserved: `{total_docx}`",
        "",
        "## Coverage by capability",
        "",
    ]
    for key in sorted(grouped):
        capability = CAPABILITY_BY_KEY[key]
        lines.append(f"- {note_link(stem_for_capability(capability['title']))}: `{len(grouped[key])}` support notes")
    lines.extend(["", "## Related notes", "", "- [[Support Articles Hub]]", "- [[Corpus Overview]]", "- [[Intelligence Home]]"])
    return "\n".join(lines)


def build_engineering_wiki_index(section_counts: dict[str, int], grouped: dict[str, list[str]]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["wiki-index"]}),
        "# Engineering Wiki Index",
        "",
        f"- Total wiki note count: `{sum(section_counts.values())}`",
        "",
    ]
    for section in sorted(section_counts):
        lines.append(f"## {section}")
        lines.append("")
        lines.append(f"- Count: `{section_counts[section]}`")
        lines.extend(f"- {link}" for link in grouped[section][:25])
        if len(grouped[section]) > 25:
            lines.append(f"- ... `{len(grouped[section]) - 25}` more pages")
        lines.append("")
    lines.extend(["## Related notes", "", "- [[Wiki Pages Hub]]", "- [[Runbook Coverage]]", "- [[Intelligence Home]]"])
    return "\n".join(lines)


def build_repo_catalog(repo_links: list[str]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["engineering", "repo-catalog"]}),
        "# Repo Catalog",
        "",
        "The authoritative code surface for this vault is the declared GitHub repository set in the product manifest.",
        "",
        f"- Repository notes: `{len(repo_links)}`",
        "",
    ]
    lines.extend(f"- {link}" for link in repo_links)
    lines.extend(["", "## Related notes", "", "- [[GitHub Source Of Truth]]", "- [[Code Intelligence Hub]]", "- [[Architecture and Service Map]]", "- [[Intelligence Home]]"])
    return "\n".join(lines)


def build_code_reference_index(grouped: dict[str, list[str]]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["engineering", "code-reference-index"]}),
        "# Code Reference Index",
        "",
        "This index links the file-level code reference notes generated from support, wiki, and capability traceability.",
        "",
    ]
    for repo_name in sorted(grouped):
        lines.append(f"## {repo_name}")
        lines.append("")
        lines.extend(f"- {link}" for link in grouped[repo_name][:80])
        if len(grouped[repo_name]) > 80:
            lines.append(f"- ... `{len(grouped[repo_name]) - 80}` more code reference notes")
        lines.append("")
    lines.extend(["## Related notes", "", "- [[Code Intelligence Hub]]", "- [[Repo Catalog]]", "- [[Support-to-Code Map]]", "- [[Conflict Log]]"])
    return "\n".join(lines)


def build_support_to_code_map(rows: list[dict[str, Any]]) -> str:
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["engineering", "traceability"]}),
        "# Support-to-Code Map",
        "",
        "This note turns the strongest recurring support and wiki themes into code-linked capability hubs.",
        "",
    ]
    for row in rows:
        lines.append(f"## {row['title']}")
        lines.append("")
        lines.append(f"- Capability note: {row['link']}")
        lines.append(f"- Support notes: `{row['support_count']}`")
        lines.append(f"- Wiki notes: `{row['wiki_count']}`")
        lines.append(f"- Code hits: `{row['code_count']}`")
        lines.append(f"- Repositories: {', '.join(f'`{repo}`' for repo in row['repos'])}")
        lines.append("")
    lines.extend(["## Related notes", "", "- [[Product Capability Map]]", "- [[Code Intelligence Hub]]", "- [[Code Reference Index]]", "- [[Conflict Log]]", "- [[Engineering Readiness]]"])
    return "\n".join(lines)


def build_research_hub() -> str:
    return "\n".join(
        [
            frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["research", "hub"]}),
            "# Research Hub",
            "",
            "- [[Support Articles Hub]]",
            "- [[Wiki Pages Hub]]",
            "- [[Code Intelligence Hub]]",
            "- [[Corpus Overview]]",
            "- [[Linked Pages Registry]]",
            "",
            "Use this hub to move from raw evidence to capability and engineering notes.",
        ]
    )


def build_source_of_truth_note(manifest: dict[str, Any], external_links: list[dict[str, Any]]) -> str:
    stale_doc_refs = [entry for entry in external_links if entry.get("status") == "stale-doc-reference"]
    stale_sources = Counter(
        source_ref
        for entry in stale_doc_refs
        for source_ref in entry.get("source_refs", [])
    )
    lines = [
        frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["engineering", "source-of-truth", "github"]}),
        "# GitHub Source Of Truth",
        "",
        "The active code source of truth for this vault is the declared GitHub repository set, not the legacy GitLab URLs embedded in older imported docs.",
        "",
        f"- Declared GitHub repositories: `{len(manifest['repositories']['items'])}`",
        f"- Legacy GitLab documentation references detected: `{len(stale_doc_refs)}`",
        "",
        "## Authoritative repositories",
        "",
    ]
    for item in manifest["repositories"]["items"]:
        lines.append(
            f"- `{item['name']}` ({item['role']}, branch `{item['default_branch']}`) -> {item['url']}"
        )
    lines.extend(
        [
            "",
            "## Documentation drift policy",
            "",
            f"- Imported wiki and support files still contain historical links from: {', '.join(sorted(STALE_DOC_HOSTS)) or 'legacy internal hosts'}.",
            "- Treat those GitLab URLs as stale documentation references unless a human confirms they still represent an active non-code system.",
            "- Use Confluence and Google Sheets as real gated operational sources when they appear; use the six declared GitHub repositories as the code surface.",
        ]
    )
    if stale_sources:
        lines.extend(["", "## Top stale-doc sources", ""])
        for source_ref, count in stale_sources.most_common(12):
            lines.append(f"- `{source_ref}`: `{count}` legacy GitLab references")
    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[Repo Catalog]]",
            "- [[Blocked Access Registry]]",
            "- [[Engineering Readiness]]",
        ]
    )
    return "\n".join(lines)


def build_conflict_log(conflicts_by_kind: dict[str, list[str]]) -> str:
    section_titles = {
        "documentation-drift": "Documentation drift",
        "restricted-source": "Restricted or incomplete sources",
        "code-traceability-gap": "Code traceability gaps",
    }
    lines = [
        frontmatter({"type": "knowledge", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["engineering", "conflicts"]}),
        "# Conflict Log",
        "",
        "This note records mismatches, documentation drift, restricted evidence, and traceability gaps discovered while rebuilding the vault.",
        "",
        "## Coverage summary",
        "",
    ]
    total_conflicts = 0
    for kind in ("documentation-drift", "restricted-source", "code-traceability-gap"):
        count = len(conflicts_by_kind.get(kind, []))
        total_conflicts += count
        lines.append(f"- {section_titles[kind]}: `{count}`")
    if total_conflicts == 0:
        lines.extend(["", "## Findings", "", "- No conflicts or traceability gaps were detected from the accessible sources."])
    else:
        for kind in ("documentation-drift", "restricted-source", "code-traceability-gap"):
            entries = conflicts_by_kind.get(kind, [])
            if not entries:
                continue
            lines.extend(["", f"## {section_titles[kind]}", ""])
            lines.extend(f"- {entry}" for entry in entries)
    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[GitHub Source Of Truth]]",
            "- [[Blocked Access Registry]]",
            "- [[Support-to-Code Map]]",
            "- [[Code Reference Index]]",
            "- [[Engineering Readiness]]",
        ]
    )
    return "\n".join(lines)


def build_home_note(total_support: int, total_wiki: int, total_capabilities: int, total_repo_notes: int, stale_doc_count: int) -> str:
    return "\n".join(
        [
            frontmatter({"type": "hub", "area": PRODUCT_CONTEXT["slug"], "source": "generated", "tags": ["home"]}),
            "# Intelligence Home",
            "",
            f"This vault is the working memory layer for {PRODUCT_CONTEXT['name']}'s support corpus, engineering wiki, and repository surface.",
            "GitHub is the declared source of truth for code. Historical GitLab links in imported docs are tracked as documentation drift.",
            "",
            "## Coverage snapshot",
            "",
            f"- Support notes: `{total_support}`",
            f"- Wiki notes: `{total_wiki}`",
            f"- Capability hubs: `{total_capabilities}`",
            f"- Repository notes: `{total_repo_notes}`",
            f"- Legacy GitLab doc references: `{stale_doc_count}`",
            "",
            "## Start here",
            "",
            "- [[Product Capability Map]]",
            "- [[Support Articles Hub]]",
            "- [[Wiki Pages Hub]]",
            "- [[Code Intelligence Hub]]",
            "- [[GitHub Source Of Truth]]",
            "- [[Engineering Readiness]]",
            "- [[Conflict Log]]",
            "- [[Blocked Access Registry]]",
            "",
            "## Research and sources",
            "",
            "- [[Corpus Overview]]",
            "- [[Support Article Index]]",
            "- [[Engineering Wiki Index]]",
            "- [[Linked Pages Registry]]",
            "",
            "## Engineering",
            "",
            "- [[Repo Catalog]]",
            "- [[Support-to-Code Map]]",
            "- [[Architecture and Service Map]]",
            "- [[Runbook Coverage]]",
        ]
    )


def build_links_by_source(external_links: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in external_links:
        for ref in entry.get("source_refs", []):
            mapping[ref].append(entry)
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild a product second brain with durable source and code notes.")
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    profile = load_product_profile(manifest)
    configure_runtime(manifest, profile)
    paths = manifest_paths(manifest)
    repo_roots = repo_lookup(manifest)
    support_inventory = read_json(paths.json_dir / "support_articles.json")
    wiki_inventory = read_json(paths.json_dir / "wiki_pages.json")
    external_links = read_json(paths.json_dir / "external_links.json")
    repo_snapshots = read_json(paths.json_dir / "repo_snapshots.json")
    docx_extracts = read_json(paths.json_dir / "docx_extracts.json")
    links_by_source = build_links_by_source(external_links)

    support_dir = paths.vault / "40 Research" / "Support Articles"
    wiki_dir = paths.vault / "40 Research" / "Wiki Pages"
    code_dir = paths.vault / "40 Research" / "Code Intelligence"
    repo_notes_dir = code_dir / "Repos"
    code_reference_dir = code_dir / "References"
    capability_dir = paths.vault / "20 Product" / "Capabilities"

    clear_markdown_dir(support_dir)
    clear_markdown_dir(wiki_dir)
    clear_markdown_dir(repo_notes_dir)
    clear_markdown_dir(code_reference_dir)
    clear_markdown_dir(capability_dir)

    ensure_dir(support_dir)
    ensure_dir(wiki_dir)
    ensure_dir(repo_notes_dir)
    ensure_dir(code_reference_dir)
    ensure_dir(capability_dir)

    article_note_stems: dict[str, str] = {}
    support_records: list[dict[str, Any]] = []
    for item in support_inventory:
        raw_path = paths.corpus / item["relative_path"]
        text = raw_path.read_text(errors="ignore")
        signals = extract_signals(text, item["title"])
        display_title = signals["title"]
        stem = stem_for_support(item, display_title)
        if item.get("article_id"):
            article_note_stems[item["article_id"]] = stem
        support_records.append(
            {
                "item": item,
                "raw_path": raw_path,
                "text": text,
                "signals": signals,
                "stem": stem,
                "capabilities": classify_capabilities(display_title, text, item["relative_path"]),
                "source_ref": item["relative_path"],
            }
        )

    wiki_records: list[dict[str, Any]] = []
    wiki_root = repo_path_by_role(manifest, "engineering-wiki")
    for item in wiki_inventory:
        raw_path = wiki_root / item["relative_path"] if wiki_root else Path(item["relative_path"])
        text = raw_path.read_text(errors="ignore")
        signals = extract_signals(text, item["title"])
        display_title = signals["title"]
        stem = stem_for_wiki(item["relative_path"], display_title)
        wiki_records.append(
            {
                "item": item,
                "raw_path": raw_path,
                "text": text,
                "signals": signals,
                "stem": stem,
                "capabilities": classify_capabilities(display_title, text, item["relative_path"]),
                "source_ref": f"wiki/{item['relative_path']}",
            }
        )

    wiki_note_stems = {
        record["item"]["relative_path"]: record["stem"]
        for record in wiki_records
    }

    support_links_by_cap: dict[str, list[str]] = defaultdict(list)
    wiki_links_by_cap: dict[str, list[str]] = defaultdict(list)
    capability_link_records: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in support_records:
        for key in record["capabilities"]:
            support_links_by_cap[key].append(note_link(record["stem"]))
            capability_link_records[key].extend(links_by_source.get(record["source_ref"], []))

    section_grouped: dict[str, list[str]] = defaultdict(list)
    for record in wiki_records:
        section = Path(record["item"]["relative_path"]).parts[0] if len(Path(record["item"]["relative_path"]).parts) > 1 else "root"
        section_grouped[section].append(note_link(record["stem"]))
        for key in record["capabilities"]:
            wiki_links_by_cap[key].append(note_link(record["stem"]))
            capability_link_records[key].extend(links_by_source.get(record["source_ref"], []))

    repo_links = [note_link(stem_for_repo(snapshot["name"])) for snapshot in repo_snapshots]

    code_hits_by_cap: dict[str, list[dict[str, Any]]] = {}
    for capability in CAPABILITIES:
        code_hits_by_cap[capability["key"]] = prune_code_hits(
            rg_code_hits(repo_roots, capability["repos"], capability["keywords"], limit=40),
            24,
        )

    repo_caps: dict[str, list[str]] = defaultdict(list)
    for capability in CAPABILITIES:
        for repo_name in capability["repos"]:
            repo_caps[repo_name].append(capability["key"])

    for record in support_records:
        repo_names = expected_repo_names(record["capabilities"])
        record["repo_names"] = repo_names
        record["code_hits"] = note_code_hits(
            repo_roots,
            repo_names,
            record["signals"],
            record["capabilities"],
            code_hits_by_cap,
        )
        record["conflicts"] = detect_note_conflicts(
            text=record["text"],
            link_records=links_by_source.get(record["source_ref"], []),
            code_hits=record["code_hits"],
            repo_names=repo_names,
        )

    for record in wiki_records:
        repo_names = expected_repo_names(record["capabilities"])
        record["repo_names"] = repo_names
        record["code_hits"] = note_code_hits(
            repo_roots,
            repo_names,
            record["signals"],
            record["capabilities"],
            code_hits_by_cap,
        )
        record["conflicts"] = detect_note_conflicts(
            text=record["text"],
            link_records=links_by_source.get(record["source_ref"], []),
            code_hits=record["code_hits"],
            repo_names=repo_names,
        )

    code_reference_registry: dict[tuple[str, str], dict[str, Any]] = {}
    capability_note_links = {
        capability["key"]: note_link(stem_for_capability(capability["title"]))
        for capability in CAPABILITIES
    }

    def register_code_hit(
        hit: dict[str, Any],
        *,
        support_link: str | None = None,
        wiki_link: str | None = None,
        capability_links: list[str] | None = None,
    ) -> None:
        key = (hit["repo"], hit["relative_path"])
        entry = code_reference_registry.setdefault(
            key,
            {
                "hit": hit,
                "support_links": [],
                "wiki_links": [],
                "capability_links": [],
            },
        )
        if support_link:
            entry["support_links"].append(support_link)
        if wiki_link:
            entry["wiki_links"].append(wiki_link)
        if capability_links:
            entry["capability_links"].extend(capability_links)

    for record in support_records:
        support_link = note_link(record["stem"])
        capability_links = [capability_note_links[key] for key in record["capabilities"]]
        for hit in record["code_hits"]:
            register_code_hit(hit, support_link=support_link, capability_links=capability_links)

    for record in wiki_records:
        wiki_link = note_link(record["stem"])
        capability_links = [capability_note_links[key] for key in record["capabilities"]]
        for hit in record["code_hits"]:
            register_code_hit(hit, wiki_link=wiki_link, capability_links=capability_links)

    for capability in CAPABILITIES:
        capability_links = [capability_note_links[capability["key"]]]
        for hit in code_hits_by_cap.get(capability["key"], []):
            register_code_hit(hit, capability_links=capability_links)

    code_reference_stems = {
        key: stem_for_code_reference(hit["repo"], hit["relative_path"])
        for key, hit in ((key, value["hit"]) for key, value in code_reference_registry.items())
    }
    code_reference_index: dict[str, list[str]] = defaultdict(list)

    for key, entry in code_reference_registry.items():
        stem = code_reference_stems[key]
        write_note(
            code_reference_dir / f"{stem}.md",
            build_code_reference_note(
                entry["hit"],
                unique_lines(entry["support_links"], 60),
                unique_lines(entry["wiki_links"], 60),
                unique_lines(entry["capability_links"], 40),
            ),
        )
        code_reference_index[entry["hit"]["repo"]].append(note_link(stem))

    conflict_entries_by_kind: dict[str, list[str]] = defaultdict(list)

    for snapshot in repo_snapshots:
        repo_path = repo_roots[snapshot["name"]]
        repo_stem = stem_for_repo(snapshot["name"])
        write_note(repo_notes_dir / f"{repo_stem}.md", build_repo_note(snapshot, repo_path, repo_caps[snapshot["name"]]))

    for record in support_records:
        repo_note_links = [note_link(stem_for_repo(repo_name)) for key in record["capabilities"] for repo_name in CAPABILITY_BY_KEY[key]["repos"]]
        repo_note_links = unique_lines(repo_note_links, 10)
        self_link = note_link(record["stem"])
        related_support_links = unique_lines(
            [
                link
                for key in record["capabilities"]
                for link in support_links_by_cap.get(key, [])
                if link != self_link
            ],
            16,
        )
        related_wiki_links = unique_lines(
            [
                link
                for key in record["capabilities"]
                for link in wiki_links_by_cap.get(key, [])
            ],
            16,
        )
        code_reference_links = [code_reference_link(hit, code_reference_stems) for hit in record["code_hits"]]
        for conflict in record["conflicts"]:
            conflict_entries_by_kind[conflict["kind"]].append(f"{note_link(record['stem'])}: {conflict['message']}")
        body = build_support_note(
            item=record["item"],
            raw_path=record["raw_path"],
            stem=record["stem"],
            capabilities=record["capabilities"],
            repo_links=repo_note_links,
            link_records=links_by_source.get(record["source_ref"], []),
            article_note_stems=article_note_stems,
            wiki_note_stems=wiki_note_stems,
            related_support_links=related_support_links,
            related_wiki_links=related_wiki_links,
            code_reference_links=code_reference_links,
            conflicts=[item["message"] for item in record["conflicts"]],
        )
        write_note(support_dir / f"{record['stem']}.md", body)

    for record in wiki_records:
        repo_note_links = [note_link(stem_for_repo(repo_name)) for key in record["capabilities"] for repo_name in CAPABILITY_BY_KEY[key]["repos"]]
        repo_note_links = unique_lines(repo_note_links, 10)
        self_link = note_link(record["stem"])
        related_support_links = unique_lines(
            [
                link
                for key in record["capabilities"]
                for link in support_links_by_cap.get(key, [])
            ],
            16,
        )
        related_wiki_links = unique_lines(
            [
                link
                for key in record["capabilities"]
                for link in wiki_links_by_cap.get(key, [])
                if link != self_link
            ],
            16,
        )
        code_reference_links = [code_reference_link(hit, code_reference_stems) for hit in record["code_hits"]]
        for conflict in record["conflicts"]:
            conflict_entries_by_kind[conflict["kind"]].append(f"{note_link(record['stem'])}: {conflict['message']}")
        body = build_wiki_note(
            relative_path=record["item"]["relative_path"],
            raw_path=record["raw_path"],
            stem=record["stem"],
            capabilities=record["capabilities"],
            repo_links=repo_note_links,
            link_records=links_by_source.get(record["source_ref"], []),
            article_note_stems=article_note_stems,
            wiki_note_stems=wiki_note_stems,
            related_support_links=related_support_links,
            related_wiki_links=related_wiki_links,
            code_reference_links=code_reference_links,
            conflicts=[item["message"] for item in record["conflicts"]],
        )
        section = Path(record["item"]["relative_path"]).parts[0] if len(Path(record["item"]["relative_path"]).parts) > 1 else "root"
        write_note(wiki_dir / section / f"{record['stem']}.md", body)

    capability_rows: list[dict[str, Any]] = []
    support_grouped_for_hub: dict[str, list[str]] = defaultdict(list)
    for key, links in support_links_by_cap.items():
        support_grouped_for_hub[key] = sorted(links)
    for capability in CAPABILITIES:
        cap_stem = stem_for_capability(capability["title"])
        support_links = sorted(support_links_by_cap.get(capability["key"], []))
        wiki_links = sorted(wiki_links_by_cap.get(capability["key"], []))
        repo_note_links = [note_link(stem_for_repo(repo_name)) for repo_name in capability["repos"]]
        code_hits = code_hits_by_cap.get(capability["key"], [])
        code_reference_links = [code_reference_link(hit, code_reference_stems) for hit in code_hits]
        body = build_capability_note(
            capability=capability,
            support_links=support_links,
            wiki_links=wiki_links,
            repo_note_links=repo_note_links,
            code_hits=code_hits,
            code_reference_links=code_reference_links,
            link_records=capability_link_records.get(capability["key"], []),
        )
        write_note(capability_dir / f"{cap_stem}.md", body)
        capability_rows.append(
            {
                "title": capability["title"],
                "link": note_link(cap_stem),
                "support_count": len(support_links),
                "wiki_count": len(wiki_links),
                "repos": capability["repos"],
                "code_count": len(code_hits),
            }
        )

    write_note(support_dir / "Support Articles Hub.md", build_support_articles_hub(support_grouped_for_hub))
    write_note(wiki_dir / "Wiki Pages Hub.md", build_wiki_pages_hub({key: sorted(value) for key, value in section_grouped.items()}))
    write_note(code_dir / "Code Intelligence Hub.md", build_code_intelligence_hub(repo_links, [row["link"] for row in capability_rows]))
    write_note(code_dir / "Code Reference Index.md", build_code_reference_index({key: sorted(value) for key, value in code_reference_index.items()}))
    write_note(paths.vault / "20 Product" / "Product Capability Map.md", build_product_capability_map(capability_rows))
    total_support_articles = sum(1 for item in support_inventory if item["category"] == "support-article")
    total_reference_docs = len(support_inventory) - total_support_articles
    write_note(paths.vault / "10 Sources" / "Support Article Index.md", build_support_article_index(total_support_articles, total_reference_docs, len(docx_extracts), support_grouped_for_hub))
    section_counts = {section: len(links) for section, links in section_grouped.items()}
    write_note(paths.vault / "10 Sources" / "Engineering Wiki Index.md", build_engineering_wiki_index(section_counts, {key: sorted(value) for key, value in section_grouped.items()}))
    write_note(paths.vault / "30 Engineering" / "Repo Catalog.md", build_repo_catalog(repo_links))
    write_note(paths.vault / "30 Engineering" / "GitHub Source Of Truth.md", build_source_of_truth_note(manifest, external_links))
    write_note(paths.vault / "30 Engineering" / "Support-to-Code Map.md", build_support_to_code_map(capability_rows))
    write_note(
        paths.vault / "30 Engineering" / "Conflict Log.md",
        build_conflict_log({key: unique_lines(value, 400) for key, value in conflict_entries_by_kind.items()}),
    )
    write_note(paths.vault / "40 Research" / "00 Research Hub.md", build_research_hub())
    stale_doc_count = sum(1 for entry in external_links if entry.get("status") == "stale-doc-reference")
    write_note(paths.vault / "00 Home" / "Intelligence Home.md", build_home_note(len(support_inventory), len(wiki_inventory), len(CAPABILITIES), len(repo_snapshots), stale_doc_count))
    sanitize_summary = sanitize_vault_notes(paths.vault)

    print(
        json.dumps(
            {
                "support_notes": len(support_records),
                "wiki_notes": len(wiki_records),
                "capability_notes": len(CAPABILITIES),
                "repo_notes": len(repo_snapshots),
                "vault": str(paths.vault),
                "vault_sanitizer": sanitize_summary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
