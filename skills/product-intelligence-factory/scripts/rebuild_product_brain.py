#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import code_intelligence
import semantic_clustering


DATE = date.today().isoformat()
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
    if not isinstance(data, dict):
        raise SystemExit(f"Profile root must be a mapping: {path}")
    capabilities = data.get("capabilities") or []
    if not isinstance(capabilities, list):
        raise SystemExit(f"Profile capabilities must be a list: {path}")
    return {
        "path": path,
        "capabilities": capabilities,
        "semantic_clustering": semantic_clustering.default_semantic_config(data),
        "code_intelligence": code_intelligence.default_code_config(data),
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


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


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


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


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


def capture_quality_score(
    *,
    signals: dict[str, Any],
    link_records: list[dict[str, Any]],
    code_reference_links: list[str],
    capabilities: list[str],
    conflicts: list[str],
) -> dict[str, Any]:
    score = 0
    factors: list[str] = []
    if capabilities:
        score += 2
        factors.append("relevance: mapped to product capabilities")
    if signals.get("headings") or signals.get("bullets"):
        score += 2
        factors.append("structure: source has sections or explicit evidence")
    if link_records:
        status_counts = Counter(record.get("status") for record in link_records)
        if status_counts.get("mirrored") or status_counts.get("local-support-evidence"):
            score += 2
            factors.append("confidence: linked evidence was captured locally")
        elif status_counts.get("blocked") or status_counts.get("auth-gated"):
            score += 1
            factors.append("confidence: some linked evidence is blocked and logged")
    if code_reference_links:
        score += 2
        factors.append("product impact: connected to implementation anchors")
    if conflicts or code_reference_links:
        score += 2
        factors.append("actionability: supports follow-up, review, or delivery work")
    rating = "high" if score >= 8 else "medium" if score >= 4 else "low"
    return {"score": min(score, 10), "rating": rating, "factors": factors or ["needs more evidence"]}


def essence_from_signals(signals: dict[str, Any], fallback: str) -> list[str]:
    lines: list[str] = []
    if signals.get("paragraphs"):
        lines.append(signals["paragraphs"][0])
    elif signals.get("bullets"):
        lines.append(signals["bullets"][0])
    else:
        lines.append(fallback)
    if signals.get("headings"):
        lines.append(f"Key sections: {', '.join(signals['headings'][:4])}.")
    return unique_lines(lines, 3)


def use_in_current_project_lines(
    *,
    capabilities: list[str],
    code_reference_links: list[str],
    conflicts: list[str],
    uncaptured_links: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    if capabilities:
        capability_titles = [CAPABILITY_BY_KEY[key]["title"] for key in capabilities if key in CAPABILITY_BY_KEY]
        lines.append(f"Use this as evidence for {', '.join(capability_titles)} work.")
    if code_reference_links:
        lines.append("Use the linked code references to scope implementation, review, testing, or support follow-up.")
    if conflicts:
        lines.append("Resolve the documented conflicts before relying on this evidence for delivery decisions.")
    if uncaptured_links:
        lines.append("Follow up on uncaptured evidence before treating this as complete source coverage.")
    if not lines:
        lines.append("Use this as reference material until it is linked to an active initiative or output.")
    return unique_lines(lines, 5)


def basb_frontmatter(
    *,
    stage: str,
    para: str,
    distillation: str,
    actionability: str,
    output_target: str = "",
) -> dict[str, str]:
    return {
        "basb_stage": stage,
        "para_category": para,
        "distillation_level": distillation,
        "actionability": actionability,
        "output_target": output_target,
    }


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


def write_generated_note(path: Path, body: str) -> None:
    if path.exists() and not is_generated_note(path):
        raise SystemExit(f"Refusing to overwrite user-authored note: {path}")
    write_note(path, body)


def clear_markdown_dir(path: Path) -> None:
    if not path.exists():
        ensure_dir(path)
        return
    for file_path in sorted(path.rglob("*.md"), reverse=True):
        file_path.unlink()
    for directory in sorted((item for item in path.rglob("*") if item.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()


def is_generated_note(path: Path) -> bool:
    text = path.read_text(errors="ignore")
    if not text.startswith("---\n"):
        return False
    head = text.split("---", 2)[1]
    return bool(re.search(r"(?m)^source:\s*[\"']?generated[\"']?\s*$", head))


def clear_generated_markdown_dir(path: Path) -> None:
    if not path.exists():
        ensure_dir(path)
        return
    for file_path in sorted(path.rglob("*.md"), reverse=True):
        if is_generated_note(file_path):
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
    symbol_count: int = 0
    route_count: int = 0
    schema_count: int = 0
    test_anchor_count: int = 0
    dependency_count: int = 0
    churn_score: int = 0
    owner_candidates: list[str] = field(default_factory=list)
    parse_quality: str = "heuristic"
    parser_backend: str = "regex-fallback"
    ast_node_count: int = 0
    line_start: int = 0
    line_end: int = 0
    imports: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    symbol_edges: list[dict[str, Any]] = field(default_factory=list)
    call_edges: list[dict[str, Any]] = field(default_factory=list)
    routes: list[dict[str, Any]] = field(default_factory=list)
    schemas: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    migrations: list[str] = field(default_factory=list)
    parser_errors: list[str] = field(default_factory=list)
    parser_limitations: list[str] = field(default_factory=list)


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


def analyze_code_reference(hit: dict[str, Any], code_file: dict[str, Any] | None = None) -> CodeReferenceAnalysis:
    path = Path(str(hit["absolute_path"]))
    text = read_code_reference_text(path)
    artifact_kind = infer_artifact_kind(hit["relative_path"], text)
    heuristic_symbols = extract_code_symbols(text)
    deep_symbols = (code_file or {}).get("symbols") or {}
    symbols = {
        "classes": unique_lines([*deep_symbols.get("classes", []), *heuristic_symbols["classes"]], 40),
        "functions": unique_lines([*deep_symbols.get("functions", []), *heuristic_symbols["functions"]], 60),
        "types": unique_lines([*deep_symbols.get("types", []), *heuristic_symbols["types"]], 60),
    }
    comments = extract_top_comment_lines(text)
    symbol_count = int((code_file or {}).get("symbol_count") or sum(len(values) for values in symbols.values()))
    return CodeReferenceAnalysis(
        artifact_kind=artifact_kind,
        language=str((code_file or {}).get("language") or infer_code_language(hit["relative_path"])),
        classes=symbols["classes"],
        functions=symbols["functions"],
        types=symbols["types"],
        comments=comments,
        implementation_signals=detect_implementation_signals(text, hit["relative_path"], artifact_kind, symbols),
        intentions=infer_intentions(hit, artifact_kind, text, symbols, comments),
        risks=detect_code_risks(text, hit["relative_path"]),
        conflicts=detect_code_conflicts(text, hit["relative_path"], artifact_kind),
        symbol_count=symbol_count,
        route_count=int((code_file or {}).get("route_count") or 0),
        schema_count=int((code_file or {}).get("schema_count") or 0),
        test_anchor_count=int((code_file or {}).get("test_anchor_count") or 0),
        dependency_count=int((code_file or {}).get("dependency_count") or 0),
        churn_score=int((code_file or {}).get("churn_score") or 0),
        owner_candidates=list((code_file or {}).get("owner_candidates") or []),
        parse_quality=str((code_file or {}).get("parse_quality") or "heuristic"),
        parser_backend=str((code_file or {}).get("parser_backend") or "regex-fallback"),
        ast_node_count=int((code_file or {}).get("ast_node_count") or 0),
        line_start=int((code_file or {}).get("line_start") or 0),
        line_end=int((code_file or {}).get("line_end") or 0),
        imports=list((code_file or {}).get("imports") or []),
        calls=list((code_file or {}).get("calls") or []),
        symbol_edges=list((code_file or {}).get("symbol_edges") or []),
        call_edges=list((code_file or {}).get("call_edges") or []),
        routes=list((code_file or {}).get("routes") or []),
        schemas=list((code_file or {}).get("schemas") or []),
        tests=list((code_file or {}).get("tests") or []),
        dependencies=list((code_file or {}).get("dependencies") or []),
        env_vars=list((code_file or {}).get("env_vars") or []),
        migrations=list((code_file or {}).get("migrations") or []),
        parser_errors=list((code_file or {}).get("parser_errors") or []),
        parser_limitations=list((code_file or {}).get("parser_limitations") or []),
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
    quality = capture_quality_score(
        signals=signals,
        link_records=link_records,
        code_reference_links=code_reference_links,
        capabilities=capabilities,
        conflicts=conflicts,
    )

    lines = [
        frontmatter(
            {
                "type": "concept",
                "area": PRODUCT_CONTEXT["slug"],
                "source": "support-export",
                "source_path": str(raw_path),
                "source_url": item.get("source_url") or "",
                "article_id": item.get("article_id") or "",
                **basb_frontmatter(
                    stage="distill",
                    para="resource",
                    distillation="distilled",
                    actionability="soon" if code_reference_links else "reference",
                ),
                "capture_quality": quality["score"],
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

    lines.extend(["", "## Essence", ""])
    lines.extend(f"- {item}" for item in essence_from_signals(signals, summary))

    lines.extend(["", "## Use in current project", ""])
    lines.extend(
        f"- {item}"
        for item in use_in_current_project_lines(
            capabilities=capabilities,
            code_reference_links=code_reference_links,
            conflicts=conflicts,
            uncaptured_links=uncaptured_links,
        )
    )

    lines.extend(["", "## Capture quality", ""])
    lines.append(f"- Score: `{quality['score']}/10`")
    lines.append(f"- Rating: `{quality['rating']}`")
    lines.extend(f"- {factor}" for factor in quality["factors"])

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
    quality = capture_quality_score(
        signals=signals,
        link_records=link_records,
        code_reference_links=code_reference_links,
        capabilities=capabilities,
        conflicts=conflicts,
    )

    lines = [
        frontmatter(
            {
                "type": "concept",
                "area": PRODUCT_CONTEXT["slug"],
                "source": "engineering-wiki",
                "source_path": str(raw_path),
                "section": Path(relative_path).parts[0] if len(Path(relative_path).parts) > 1 else "root",
                **basb_frontmatter(
                    stage="distill",
                    para="resource",
                    distillation="distilled",
                    actionability="soon" if code_reference_links else "reference",
                ),
                "capture_quality": quality["score"],
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

    lines.extend(["", "## Essence", ""])
    lines.extend(f"- {item}" for item in essence_from_signals(signals, summary))

    lines.extend(["", "## Use in current project", ""])
    lines.extend(
        f"- {item}"
        for item in use_in_current_project_lines(
            capabilities=capabilities,
            code_reference_links=code_reference_links,
            conflicts=conflicts,
            uncaptured_links=uncaptured_links,
        )
    )

    lines.extend(["", "## Capture quality", ""])
    lines.append(f"- Score: `{quality['score']}/10`")
    lines.append(f"- Rating: `{quality['rating']}`")
    lines.extend(f"- {factor}" for factor in quality["factors"])

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
                **basb_frontmatter(
                    stage="organize",
                    para="resource",
                    distillation="highlighted",
                    actionability="reference",
                ),
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
    code_file: dict[str, Any] | None = None,
) -> str:
    analysis = analyze_code_reference(hit, code_file=code_file)
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
                "symbol_count": analysis.symbol_count,
                "route_count": analysis.route_count,
                "schema_count": analysis.schema_count,
                "test_anchor_count": analysis.test_anchor_count,
                "dependency_count": analysis.dependency_count,
                "churn_score": analysis.churn_score,
                "owner_candidates": analysis.owner_candidates,
                "parse_quality": analysis.parse_quality,
                "parser_backend": analysis.parser_backend,
                "ast_node_count": analysis.ast_node_count,
                "line_start": analysis.line_start,
                "line_end": analysis.line_end,
                **basb_frontmatter(
                    stage="distill",
                    para="resource",
                    distillation="distilled",
                    actionability="soon" if support_links or wiki_links else "reference",
                ),
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
    lines.extend(["", "## Essence", ""])
    lines.extend(f"- {item}" for item in analysis.intentions[:3])
    lines.extend(["", "## Use in current project", ""])
    if support_links or wiki_links:
        lines.append("- Use this implementation anchor to scope related support, wiki, review, or delivery work.")
    else:
        lines.append("- Use this as a reusable code reference until it is connected to an active output or initiative.")
    if analysis.risks:
        lines.append("- Review the detected risk signals before relying on this path for shipping work.")
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

    lines.extend(["", "## Symbols", ""])
    if analysis.classes:
        lines.append(f"- Classes/modules/structs: {', '.join(f'`{name}`' for name in analysis.classes[:20])}")
    if analysis.functions:
        lines.append(f"- Functions/methods/entrypoints: {', '.join(f'`{name}`' for name in analysis.functions[:30])}")
    if analysis.types:
        lines.append(f"- Types/schema objects: {', '.join(f'`{name}`' for name in analysis.types[:30])}")
    if not any((analysis.classes, analysis.functions, analysis.types)):
        lines.append("- No symbols were extracted from this file.")

    lines.extend(["", "## Route and API surfaces", ""])
    if analysis.routes:
        for route in analysis.routes[:40]:
            lines.append(f"- `{route.get('method', 'HTTP')} {route.get('path', '')}`")
    else:
        lines.append("- No route or API surface was extracted from this file.")

    lines.extend(["", "## Schema and data contracts", ""])
    if analysis.schemas:
        for schema in analysis.schemas[:40]:
            lines.append(f"- `{schema.get('kind', 'schema')}`: `{schema.get('name', '')}`")
    if analysis.env_vars:
        lines.append(f"- Environment variables: {', '.join(f'`{name}`' for name in analysis.env_vars[:30])}")
    if analysis.migrations:
        lines.extend(f"- Migration signal: {signal}" for signal in analysis.migrations[:10])
    if not any((analysis.schemas, analysis.env_vars, analysis.migrations)):
        lines.append("- No schema, data-contract, env-var, or migration surface was extracted from this file.")

    lines.extend(["", "## Inbound and outbound calls", ""])
    if analysis.imports:
        lines.append(f"- Imports/requires: {', '.join(f'`{name}`' for name in analysis.imports[:30])}")
    if analysis.calls:
        lines.append(f"- Calls detected: {', '.join(f'`{name}`' for name in analysis.calls[:40])}")
    if analysis.call_edges:
        lines.extend(
            f"- Call edge: `{edge.get('from', hit['relative_path'])}` -> `{edge.get('to', '')}`"
            for edge in analysis.call_edges[:20]
        )
    if not analysis.imports and not analysis.calls:
        lines.append("- No imports or call anchors were extracted from this file.")

    lines.extend(["", "## Test anchors", ""])
    if analysis.tests:
        for test in analysis.tests[:30]:
            lines.append(f"- `{test.get('kind', 'test')}`: `{test.get('name', '')}`")
    else:
        lines.append("- No direct test anchors were extracted for this file.")

    lines.extend(["", "## Dependencies", ""])
    if analysis.dependencies:
        lines.extend(f"- `{dependency}`" for dependency in analysis.dependencies[:40])
    else:
        lines.append("- No dependency edges were extracted for this file.")

    lines.extend(["", "## Ownership and churn", ""])
    lines.append(f"- Churn score: `{analysis.churn_score}/10`")
    if analysis.owner_candidates:
        lines.append(f"- Likely owners from git history: {', '.join(f'`{owner}`' for owner in analysis.owner_candidates[:5])}")
    else:
        lines.append("- No likely owner candidates were available from local git history.")

    lines.extend(["", "## Parser limitations", ""])
    lines.append(f"- Parse quality: `{analysis.parse_quality}`")
    lines.append(f"- Parser backend: `{analysis.parser_backend}`")
    lines.append(f"- AST nodes: `{analysis.ast_node_count}`")
    if analysis.line_start and analysis.line_end:
        lines.append(f"- File line range: `{analysis.line_start}-{analysis.line_end}`")
    if analysis.symbol_edges:
        lines.append(f"- AST symbol anchors: `{len(analysis.symbol_edges)}`")
    if analysis.call_edges:
        lines.append(f"- AST call anchors: `{len(analysis.call_edges)}`")
    if analysis.parser_errors:
        lines.extend(f"- {error}" for error in analysis.parser_errors[:5])
    if analysis.parser_limitations:
        lines.extend(f"- {limitation}" for limitation in analysis.parser_limitations[:5])
    else:
        lines.append("- This is a broad static scan, not compiler-grade whole-program analysis.")

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
                **basb_frontmatter(
                    stage="organize",
                    para="area",
                    distillation="executive",
                    actionability="soon",
                ),
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
    lines.extend(["", "## Essence", ""])
    lines.append(f"- This capability groups evidence and implementation anchors for {capability['title']}.")
    lines.extend(["", "## Use in current project", ""])
    if code_reference_links:
        lines.append("- Use the representative code paths to scope implementation, review, and testing work.")
    else:
        lines.append("- Use this as a capability map until direct code evidence is available.")
    lines.append("- Convert strong evidence clusters into intermediate packets or shippable output candidates.")
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


def score_packet_evidence(
    *,
    support_links: list[str],
    wiki_links: list[str],
    code_reference_links: list[str],
    conflict_count: int = 0,
    stale_doc_count: int = 0,
) -> int:
    score = 0
    if support_links:
        score += min(3, len(support_links))
    if wiki_links:
        score += min(2, len(wiki_links))
    if code_reference_links:
        score += 3
    if conflict_count:
        score += min(2, conflict_count)
    if stale_doc_count:
        score += min(2, stale_doc_count)
    return min(score, 10)


def build_intermediate_packet_note(
    capability: dict[str, Any],
    support_links: list[str],
    wiki_links: list[str],
    repo_note_links: list[str],
    code_reference_links: list[str],
    *,
    packet_kind: str = "capability",
    conflict_links: list[str] | None = None,
    stale_doc_count: int = 0,
    evidence_score: int | None = None,
    output_candidate_links: list[str] | None = None,
) -> str:
    conflict_links = conflict_links or []
    output_candidate_links = output_candidate_links or []
    score = evidence_score if evidence_score is not None else score_packet_evidence(
        support_links=support_links,
        wiki_links=wiki_links,
        code_reference_links=code_reference_links,
        conflict_count=len(conflict_links),
        stale_doc_count=stale_doc_count,
    )
    lines = [
        frontmatter(
            {
                "type": "intermediate-packet",
                "area": PRODUCT_CONTEXT["slug"],
                "status": "reusable",
                "date": DATE,
                "source": "generated",
                "packet_kind": packet_kind,
                "evidence_score": score,
                "generated_output_candidates": output_candidate_links,
                **basb_frontmatter(
                    stage="distill",
                    para="resource",
                    distillation="executive",
                    actionability="soon",
                    output_target="Output Pipeline",
                ),
                "tags": ["intermediate-packet", capability["key"]],
            }
        ),
        f"# {capability['title']} Intermediate Packet",
        "",
        "## Essence",
        "",
        f"- {capability['description']}",
        f"- Evidence coverage: `{len(support_links)}` support notes, `{len(wiki_links)}` wiki notes, `{len(code_reference_links)}` code references.",
        f"- Evidence score: `{score}/10`.",
        "",
        "## Highlights",
        "",
        f"- Support evidence: `{len(support_links)}` linked note(s).",
        f"- Wiki evidence: `{len(wiki_links)}` linked note(s).",
        f"- Code evidence: `{len(code_reference_links)}` implementation anchor(s).",
        f"- Conflict or drift signals: `{len(conflict_links) + stale_doc_count}`.",
        "",
        "## Distilled takeaways",
        "",
        "- Treat this packet as a reusable synthesis layer before opening the full raw evidence.",
        "- Use linked implementation anchors to verify whether the evidence is current before shipping work.",
        "",
        "## Executive use",
        "",
        "- Promote this packet into an output candidate when the evidence score, code links, or conflict signals justify delivery follow-up.",
        "",
        "## Reusable building block",
        "",
        "- Use this packet to brief product work, support follow-up, implementation planning, review, or runbook drafting.",
        "- Keep delivery artifacts in the system of record and link them back here as `output_target` values.",
        "",
        "## Source evidence",
        "",
    ]
    if support_links:
        lines.extend(f"- {link}" for link in support_links[:20])
    if wiki_links:
        lines.extend(f"- {link}" for link in wiki_links[:20])
    if code_reference_links:
        lines.extend(f"- {link}" for link in code_reference_links[:20])
    if conflict_links:
        lines.extend(f"- {link}" for link in conflict_links[:20])
    if not any((support_links, wiki_links, code_reference_links)):
        lines.append("- No source evidence was generated for this capability yet.")
    lines.extend(["", "## Implementation anchors", ""])
    if repo_note_links:
        lines.extend(f"- {link}" for link in repo_note_links)
    else:
        lines.append("- No repository notes are linked yet.")
    lines.extend(
        [
            "",
            "## Can feed",
            "",
            "- [[Output Pipeline]]",
            "- [[Product Capability Map]]",
            "- [[Support-to-Code Map]]",
            *output_candidate_links[:12],
            "",
            "## Related notes",
            "",
            "- [[Intermediate Packet Index]]",
            "- [[CODE Dashboard]]",
        ]
    )
    return "\n".join(lines)


def build_intermediate_packet_index(packet_links: list[str]) -> str:
    lines = [
        frontmatter(
            {
                "type": "hub",
                "area": PRODUCT_CONTEXT["slug"],
                "source": "generated",
                **basb_frontmatter(
                    stage="distill",
                    para="resource",
                    distillation="executive",
                    actionability="soon",
                    output_target="Output Pipeline",
                ),
                "tags": ["intermediate-packet", "hub"],
            }
        ),
        "# Intermediate Packet Index",
        "",
        "Intermediate packets are reusable support, wiki, code, and planning clusters that can feed future product work.",
        "",
        f"- Packets generated: `{len(packet_links)}`",
        "",
        "## Packets",
        "",
    ]
    lines.extend(f"- {link}" for link in sorted(packet_links))
    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[Output Pipeline]]",
            "- [[Product Capability Map]]",
            "- [[Support-to-Code Map]]",
            "- [[Code Intelligence Hub]]",
        ]
    )
    return "\n".join(lines)


def infer_output_kind(packet: dict[str, Any]) -> str:
    if packet.get("conflict_kind") == "documentation-drift" or packet.get("stale_doc_count", 0):
        return "runbook"
    if packet.get("conflict_kind") in {"restricted-source", "code-traceability-gap"}:
        return "ticket"
    if packet.get("code_reference_links"):
        return "pull-request-plan"
    if packet.get("support_links") and packet.get("wiki_links"):
        return "spec"
    return "prd"


def shipping_path_for_kind(output_kind: str) -> str:
    return {
        "prd": "Draft a PRD in the product planning system and link it back to this vault note.",
        "spec": "Draft a product or engineering spec and link the approved artifact as the output target.",
        "ticket": "Create an implementation or investigation ticket in the delivery system of record.",
        "pull-request-plan": "Use this as the pull request plan or review checklist before opening code changes.",
        "runbook": "Turn this into a support, operations, or documentation-maintenance runbook.",
        "decision": "Convert the recommendation into a decision note and link the decision owner.",
        "launch-note": "Use this evidence to draft launch notes once the work ships.",
        "post-launch-learning": "Capture outcome evidence after release and archive reusable learnings.",
    }.get(output_kind, "Turn this output draft into the appropriate delivery artifact and link the system-of-record item.")


def stem_for_output_candidate(title: str) -> str:
    return safe_filename(f"Output Candidate - {title}", limit=160)


def select_output_candidates(packet_records: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    promotable = [
        packet
        for packet in packet_records
        if packet.get("evidence_score", 0) >= 5
        or packet.get("packet_kind") == "semantic-cluster"
        or float(packet.get("semantic_cluster_score", 0) or 0) >= 0.78
        or packet.get("code_reference_links")
        or packet.get("conflict_count", 0)
        or packet.get("stale_doc_count", 0)
    ]
    ranked = sorted(
        promotable,
        key=lambda packet: (
            -int(packet.get("evidence_score", 0)),
            -float(packet.get("semantic_cluster_score", 0) or 0),
            -len(packet.get("code_reference_links", [])),
            -int(packet.get("conflict_count", 0)),
            packet.get("title", ""),
        ),
    )
    return ranked[:limit]


def build_output_candidate_note(packet: dict[str, Any]) -> str:
    output_kind = infer_output_kind(packet)
    title = f"{packet['title']} Output Candidate"
    evidence_links = unique_lines(
        [
            packet["link"],
            *packet.get("support_links", []),
            *packet.get("wiki_links", []),
            *packet.get("code_reference_links", []),
            *packet.get("conflict_links", []),
        ],
        40,
    )
    lines = [
        frontmatter(
            {
                "type": "output",
                "area": PRODUCT_CONTEXT["slug"],
                "status": "proposed",
                "date": DATE,
                "source": "generated",
                "output_kind": output_kind,
                "source_packet": packet["link"],
                "evidence_score": packet.get("evidence_score", 0),
                "shipping_path": shipping_path_for_kind(output_kind),
                **basb_frontmatter(
                    stage="express",
                    para="project",
                    distillation="executive",
                    actionability="now",
                    output_target="vault-draft",
                ),
                "tags": ["output", output_kind, "generated"],
            }
        ),
        f"# {title}",
        "",
        "## Output type",
        output_kind,
        "",
        "## Decision or ask",
        "",
        f"- Convert {packet['link']} into a shippable `{output_kind}` if the linked evidence still reflects current product reality.",
        "",
        "## Evidence",
        "",
    ]
    lines.extend(f"- {link}" for link in evidence_links)
    lines.extend(
        [
            "",
            "## Shipping path",
            "",
            f"- {shipping_path_for_kind(output_kind)}",
            "- Keep GitHub, Jira, Linear, or the support system as the system of record; keep this note as the reasoning and evidence layer.",
            "",
            "## Related initiative",
            "",
            "- [[Active Bets]]",
            "",
            "## Source packet",
            "",
            f"- {packet['link']}",
            "",
            "## Related notes",
            "",
            "- [[Output Pipeline]]",
            "- [[Intermediate Packet Index]]",
            "- [[Weekly Synthesis]]",
        ]
    )
    return "\n".join(lines)


def build_packet_note_from_spec(spec: dict[str, Any], output_candidate_links: list[str]) -> str:
    if spec["kind"] == "semantic":
        return build_semantic_packet_note(spec["cluster"], output_candidate_links=output_candidate_links)
    return build_intermediate_packet_note(
        capability=spec["capability"],
        support_links=spec["support_links"],
        wiki_links=spec["wiki_links"],
        repo_note_links=spec["repo_note_links"],
        code_reference_links=spec["code_reference_links"],
        packet_kind=spec["packet_kind"],
        conflict_links=spec["conflict_links"],
        stale_doc_count=spec["stale_doc_count"],
        evidence_score=spec["evidence_score"],
        output_candidate_links=output_candidate_links,
    )


def build_weekly_review_note(
    packet_records: list[dict[str, Any]],
    output_records: list[dict[str, Any]],
    stale_doc_refs: list[dict[str, Any]],
    conflicts_by_kind: dict[str, list[str]],
) -> str:
    top_packets = sorted(packet_records, key=lambda packet: (-int(packet.get("evidence_score", 0)), packet["title"]))[:12]
    lines = [
        frontmatter(
            {
                "type": "review",
                "area": PRODUCT_CONTEXT["slug"],
                "status": "active",
                "date": DATE,
                "source": "generated",
                "review_period": "weekly",
                **basb_frontmatter(
                    stage="distill",
                    para="resource",
                    distillation="executive",
                    actionability="now",
                    output_target="Output Pipeline",
                ),
                "tags": ["weekly-review", "generated"],
            }
        ),
        f"# Weekly Review - {DATE}",
        "",
        "## CODE movement",
        "",
        f"- Reusable packets generated: `{len(packet_records)}`",
        f"- Output candidates generated: `{len(output_records)}`",
        f"- Stale source references found: `{len(stale_doc_refs)}`",
        f"- Conflict groups: `{sum(1 for entries in conflicts_by_kind.values() if entries)}`",
        "",
        "## New or high-value packets",
        "",
    ]
    if top_packets:
        lines.extend(f"- {packet['link']} (score `{packet.get('evidence_score', 0)}/10`)" for packet in top_packets)
    else:
        lines.append("- No packets were generated in this rebuild.")
    lines.extend(["", "## Output candidates", ""])
    if output_records:
        lines.extend(f"- {record['link']} ({record['output_kind']}, score `{record['evidence_score']}/10`)" for record in output_records)
    else:
        lines.append("- No output candidates were generated from the current evidence.")
    lines.extend(["", "## Unresolved evidence gaps", ""])
    for kind, entries in sorted(conflicts_by_kind.items()):
        if entries:
            lines.append(f"- {kind}: `{len(entries)}` finding(s)")
    if not any(conflicts_by_kind.values()):
        lines.append("- No conflict groups were generated from the current evidence.")
    lines.extend(["", "## Stale sources", ""])
    if stale_doc_refs:
        for entry in stale_doc_refs[:12]:
            refs = ", ".join(f"`{ref}`" for ref in entry.get("source_refs", [])[:3])
            lines.append(f"- {entry.get('url', '(missing url)')} from {refs or '`unknown source`'}")
    else:
        lines.append("- No stale documentation references were detected.")
    lines.extend(
        [
            "",
            "## Next review actions",
            "",
            "- Promote the strongest output candidates into the delivery system of record.",
            "- Resolve high-impact stale or restricted evidence before relying on it for delivery decisions.",
            "- Archive completed work only after outcomes and reusable learnings are captured.",
            "",
            "## Related notes",
            "",
            "- [[Output Pipeline]]",
            "- [[Intermediate Packet Index]]",
            "- [[Archive Index]]",
            "- [[CODE Dashboard]]",
        ]
    )
    return "\n".join(lines)


def build_stale_sources_archive_note(stale_doc_refs: list[dict[str, Any]]) -> str:
    source_counts = Counter(
        source_ref
        for entry in stale_doc_refs
        for source_ref in entry.get("source_refs", [])
    )
    lines = [
        frontmatter(
            {
                "type": "archive-record",
                "area": PRODUCT_CONTEXT["slug"],
                "status": "archived",
                "date": DATE,
                "source": "generated",
                "archive_reason": "stale-documentation",
                **basb_frontmatter(
                    stage="archive",
                    para="archive",
                    distillation="executive",
                    actionability="reference",
                    output_target="GitHub Source Of Truth",
                ),
                "tags": ["archive", "stale-sources", "generated"],
            }
        ),
        f"# Stale Sources - {DATE}",
        "",
        "## Archive reason",
        "",
        "- Imported evidence still references stale documentation hosts. Keep this record as drift evidence; do not treat stale links as active code source-of-truth.",
        "",
        "## Summary",
        "",
        f"- Stale references detected: `{len(stale_doc_refs)}`",
        f"- Source notes affected: `{len(source_counts)}`",
        "",
        "## Top affected sources",
        "",
    ]
    if source_counts:
        lines.extend(f"- `{source}`: `{count}` stale reference(s)" for source, count in source_counts.most_common(20))
    else:
        lines.append("- No source references were attached to stale links.")
    lines.extend(["", "## Stale reference samples", ""])
    for entry in stale_doc_refs[:30]:
        lines.append(f"- {entry.get('url', '(missing url)')}")
    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[GitHub Source Of Truth]]",
            "- [[Conflict Log]]",
            "- [[Archive Index]]",
            "- [[Weekly Synthesis]]",
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
        "## Deep maps",
        "",
        "- [[Route Map]]",
        "- [[Schema And Data Model Map]]",
        "- [[Call Graph Map]]",
        "- [[Dependency Graph Map]]",
        "- [[Test Coverage Map]]",
        "- [[Ownership And Churn Map]]",
        "",
        "## Repository notes",
        "",
    ]
    lines.extend(f"- {link}" for link in repo_links)
    lines.extend(["", "## Capability notes", ""])
    lines.extend(f"- {link}" for link in capability_links)
    lines.extend(["", "## Related notes", "", "- [[Code Reference Index]]", "- [[Repo Catalog]]", "- [[GitHub Source Of Truth]]", "- [[Support-to-Code Map]]", "- [[Conflict Log]]", "- [[Intelligence Home]]"])
    return "\n".join(lines)


def build_code_map_note(title: str, description: str, lines_body: list[str], tags: list[str]) -> str:
    lines = [
        frontmatter(
            {
                "type": "hub",
                "area": PRODUCT_CONTEXT["slug"],
                "source": "generated",
                **basb_frontmatter(
                    stage="distill",
                    para="resource",
                    distillation="executive",
                    actionability="soon",
                    output_target="Code Intelligence Hub",
                ),
                "tags": ["code-intelligence", *tags],
            }
        ),
        f"# {title}",
        "",
        description,
        "",
        *lines_body,
        "",
        "## Related notes",
        "",
        "- [[Code Intelligence Hub]]",
        "- [[Code Reference Index]]",
        "- [[Repo Catalog]]",
        "- [[Engineering Readiness]]",
    ]
    return "\n".join(lines)


def build_route_map(code_intel: dict[str, Any]) -> str:
    route_rows = [
        (item["repo"], item["relative_path"], route.get("method", "HTTP"), route.get("path", ""))
        for item in code_intel.get("files", [])
        for route in item.get("routes", [])
    ]
    body = [
        f"- Routes extracted: `{len(route_rows)}`",
        "",
        "## Route surfaces",
        "",
    ]
    if route_rows:
        for repo, relative_path, method, route_path in route_rows[:250]:
            body.append(f"- `{method} {route_path}` -> `{repo}/{relative_path}`")
    else:
        body.append("- No route surfaces were extracted from the scanned code.")
    return build_code_map_note("Route Map", "Generated route/API surfaces extracted from local repository scans.", body, ["routes"])


def build_schema_map(code_intel: dict[str, Any]) -> str:
    schema_rows = [
        (item["repo"], item["relative_path"], schema.get("kind", "schema"), schema.get("name", ""))
        for item in code_intel.get("files", [])
        for schema in item.get("schemas", [])
    ]
    body = [
        f"- Schema/data contract entries: `{len(schema_rows)}`",
        "",
        "## Schema and data model surfaces",
        "",
    ]
    if schema_rows:
        for repo, relative_path, kind, name in schema_rows[:300]:
            body.append(f"- `{kind}` `{name}` -> `{repo}/{relative_path}`")
    else:
        body.append("- No schema or data-contract surfaces were extracted from the scanned code.")
    return build_code_map_note("Schema And Data Model Map", "Generated schema, data-contract, and migration surfaces extracted from local repository scans.", body, ["schemas"])


def build_call_graph_map(code_intel: dict[str, Any]) -> str:
    edges = code_intel.get("graph", {}).get("calls", [])
    body = [
        f"- Call edges extracted: `{len(edges)}`",
        "",
        "## Representative call edges",
        "",
    ]
    if edges:
        for edge in edges[:300]:
            body.append(f"- `{edge.get('from', '')}` -> `{edge.get('to', '')}`")
    else:
        body.append("- No call edges were extracted from the scanned code.")
    return build_code_map_note("Call Graph Map", "Generated lightweight call anchors from broad static scans. This is not compiler-grade whole-program call resolution.", body, ["calls", "graph"])


def build_dependency_graph_map(code_intel: dict[str, Any]) -> str:
    edges = code_intel.get("graph", {}).get("dependencies", [])
    body = [
        f"- Dependency edges extracted: `{len(edges)}`",
        "",
        "## Representative dependency edges",
        "",
    ]
    if edges:
        for edge in edges[:300]:
            body.append(f"- `{edge.get('from', '')}` -> `{edge.get('to', '')}`")
    else:
        body.append("- No dependency edges were extracted from manifests or imports.")
    return build_code_map_note("Dependency Graph Map", "Generated dependency edges from imports, package manifests, and dependency declarations.", body, ["dependencies", "graph"])


def build_test_coverage_map(code_intel: dict[str, Any]) -> str:
    test_rows = [
        (item["repo"], item["relative_path"], test.get("kind", "test"), test.get("name", ""))
        for item in code_intel.get("files", [])
        for test in item.get("tests", [])
    ]
    files_with_tests = {f"{repo}/{relative_path}" for repo, relative_path, _, _ in test_rows}
    body = [
        f"- Test anchors extracted: `{len(test_rows)}`",
        f"- Files with direct test anchors: `{len(files_with_tests)}`",
        "",
        "## Test anchors",
        "",
    ]
    if test_rows:
        for repo, relative_path, kind, name in test_rows[:250]:
            body.append(f"- `{kind}` `{name}` -> `{repo}/{relative_path}`")
    else:
        body.append("- No direct test anchors were extracted from the scanned code.")
    return build_code_map_note("Test Coverage Map", "Generated test anchors and coverage clues. Treat gaps as prompts for review, not proof that behavior is untested.", body, ["tests"])


def build_ownership_churn_map(code_intel: dict[str, Any]) -> str:
    ranked = sorted(
        code_intel.get("files", []),
        key=lambda item: (-int(item.get("churn_score", 0)), item.get("repo", ""), item.get("relative_path", "")),
    )
    owners = Counter(
        owner
        for item in code_intel.get("files", [])
        for owner in item.get("owner_candidates", [])
    )
    body = [
        f"- Files with git churn: `{sum(1 for item in ranked if int(item.get('churn_score', 0)) > 0)}`",
        "",
        "## Likely owners",
        "",
    ]
    if owners:
        body.extend(f"- `{owner}`: `{count}` file touch signal(s)" for owner, count in owners.most_common(30))
    else:
        body.append("- No likely owners were available from local git history.")
    body.extend(["", "## Highest churn files", ""])
    high_churn = [item for item in ranked if int(item.get("churn_score", 0)) > 0][:80]
    if high_churn:
        for item in high_churn:
            owners_text = ", ".join(f"`{owner}`" for owner in item.get("owner_candidates", [])[:3]) or "`unknown`"
            body.append(f"- `{item['repo']}/{item['relative_path']}`: churn `{item.get('churn_score', 0)}/10`, owners {owners_text}")
    else:
        body.append("- No high-churn files were detected from local git history.")
    return build_code_map_note("Ownership And Churn Map", "Generated ownership and churn clues from local git history.", body, ["ownership", "churn"])


def code_terms_for_file(code_file: dict[str, Any] | None) -> list[str]:
    if not code_file:
        return []
    terms: list[str] = []
    symbols = code_file.get("symbols") or {}
    for values in symbols.values():
        terms.extend(values[:20])
    terms.extend(route.get("path", "") for route in code_file.get("routes", [])[:20])
    terms.extend(schema.get("name", "") for schema in code_file.get("schemas", [])[:20])
    terms.extend(code_file.get("dependencies", [])[:20])
    return unique_lines([term for term in terms if term], 60)


def semantic_terms_from_record(record: dict[str, Any]) -> list[str]:
    signals = record.get("signals") or {}
    terms: list[str] = [signals.get("title", "")]
    terms.extend(signals.get("headings", [])[:8])
    terms.extend(signals.get("bullets", [])[:6])
    terms.extend(Path(record.get("source_ref", "")).parts[:4])
    return unique_lines([term for term in terms if term], 30)


def build_semantic_evidence_cards(
    support_records: list[dict[str, Any]],
    wiki_records: list[dict[str, Any]],
    code_reference_registry: dict[tuple[str, str], dict[str, Any]],
    code_reference_stems: dict[tuple[str, str], str],
    code_intel_by_path: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for kind, records in (("support", support_records), ("wiki", wiki_records)):
        for record in records:
            code_terms: list[str] = []
            for hit in record.get("code_hits", [])[:8]:
                code_terms.extend([hit.get("repo", ""), hit.get("relative_path", "")])
                code_terms.extend(code_terms_for_file(code_intel_by_path.get((hit.get("repo", ""), hit.get("relative_path", ""))))[:20])
            cards.append(
                {
                    "id": f"{kind}:{record['source_ref']}",
                    "kind": kind,
                    "title": record.get("signals", {}).get("title") or record["item"].get("title", record["source_ref"]),
                    "summary": " ".join(essence_from_signals(record.get("signals", {}), record.get("source_ref", ""))),
                    "link": note_link(record["stem"]),
                    "capabilities": [CAPABILITY_BY_KEY[key]["title"] for key in record.get("capabilities", []) if key in CAPABILITY_BY_KEY],
                    "evidence_terms": semantic_terms_from_record(record),
                    "code_terms": unique_lines(code_terms, 60),
                    "code_reference_links": record.get("code_reference_links", []),
                    "source_links": [note_link(record["stem"])],
                }
            )
    for key, entry in code_reference_registry.items():
        hit = entry["hit"]
        code_file = code_intel_by_path.get(key)
        analysis = analyze_code_reference(hit, code_file=code_file)
        cards.append(
            {
                "id": f"code:{hit['repo']}:{hit['relative_path']}",
                "kind": "code",
                "title": f"{hit['repo']}/{hit['relative_path']}",
                "summary": " ".join(analysis.intentions[:3]),
                "link": note_link(code_reference_stems[key]),
                "capabilities": unique_lines(
                    [link.replace("[[Capability - ", "").replace("]]", "") for link in entry.get("capability_links", [])],
                    20,
                ),
                "evidence_terms": unique_lines([analysis.artifact_kind, analysis.language, *analysis.implementation_signals], 40),
                "code_terms": code_terms_for_file(code_file),
                "code_reference_links": [note_link(code_reference_stems[key])],
                "source_links": [note_link(code_reference_stems[key])],
            }
        )
    return cards


def build_semantic_packet_note(cluster: dict[str, Any], output_candidate_links: list[str] | None = None) -> str:
    cards = cluster.get("cards", [])
    evidence_links = unique_lines(
        [link for card in cards for link in card.get("source_links", [])] +
        [card.get("link", "") for card in cards],
        60,
    )
    code_reference_links = unique_lines(
        [link for card in cards for link in card.get("code_reference_links", [])],
        60,
    )
    code_terms = unique_lines(
        [term for card in cards for term in card.get("code_terms", [])],
        80,
    )
    output_candidate_links = output_candidate_links or []
    lines = [
        frontmatter(
            {
                "type": "intermediate-packet",
                "area": PRODUCT_CONTEXT["slug"],
                "status": "reusable",
                "date": DATE,
                "source": "generated",
                "packet_kind": "semantic-cluster",
                "semantic_cluster_score": cluster.get("similarity_score", 0),
                "evidence_score": cluster.get("evidence_score", 0),
                "llm_synthesis_status": cluster.get("llm_synthesis_status", "unknown"),
                "llm_model": cluster.get("llm_model", ""),
                "generated_output_candidates": output_candidate_links,
                **basb_frontmatter(
                    stage="distill",
                    para="resource",
                    distillation="executive",
                    actionability="soon",
                    output_target="Output Pipeline",
                ),
                "tags": ["intermediate-packet", "semantic-cluster"],
            }
        ),
        f"# {cluster.get('theme', 'Semantic Evidence Cluster')} Semantic Packet",
        "",
        "## Theme",
        "",
        f"- {cluster.get('theme', 'Semantic Evidence Cluster')}",
        f"- Semantic similarity score: `{cluster.get('similarity_score', 0)}`",
        f"- Evidence score: `{cluster.get('evidence_score', 0)}/10`",
        "",
        "## Why this cluster exists",
        "",
        f"- {cluster.get('why_this_cluster_exists') or 'These sources were grouped by OpenAI embeddings over compact evidence cards drawn from support, wiki, code-reference, and generated-note context.'}",
        "- The cluster is meant to reveal reusable work themes across sources that may not use the same wording.",
        "",
    ]
    if cluster.get("llm_summary"):
        lines.extend(["", "## LLM synthesis", "", f"- {cluster['llm_summary']}"])
    if cluster.get("merge_split_recommendation") or cluster.get("output_candidate_rationale"):
        lines.extend(["", "## Synthesis guidance", ""])
        if cluster.get("merge_split_recommendation"):
            lines.append(f"- Merge/split: {cluster['merge_split_recommendation']}")
        if cluster.get("output_candidate_rationale"):
            lines.append(f"- Output rationale: {cluster['output_candidate_rationale']}")
    lines.extend(
        [
            "",
            "## Synthesis status",
            "",
            f"- LLM synthesis status: `{cluster.get('llm_synthesis_status', 'unknown')}`",
            f"- LLM model: `{cluster.get('llm_model', '')}`",
            "",
            "## Cross-source evidence",
            "",
        ]
    )
    if evidence_links:
        lines.extend(f"- {link}" for link in evidence_links[:60])
    else:
        lines.append("- No source links were attached to this semantic cluster.")
    lines.extend(["", "## Related code surfaces", ""])
    if code_reference_links:
        lines.extend(f"- {link}" for link in code_reference_links[:40])
    if code_terms:
        lines.append(f"- Extracted code terms: {', '.join(f'`{term}`' for term in code_terms[:30])}")
    if not code_reference_links and not code_terms:
        lines.append("- No code surfaces were attached to this semantic cluster.")
    lines.extend(["", "## Output candidates", ""])
    if output_candidate_links:
        lines.extend(f"- {link}" for link in output_candidate_links[:12])
    else:
        lines.append("- [[Output Pipeline]]")
    lines.extend(["", "## Cluster limitations", ""])
    limitations = cluster.get("limitations") or []
    if limitations:
        lines.extend(f"- {limitation}" for limitation in limitations)
    else:
        lines.append("- Review linked evidence before using this semantic packet for delivery work.")
    lines.extend(
        [
            "",
            "## Can feed",
            "",
            "- [[Output Pipeline]]",
            "- [[Intermediate Packet Index]]",
            "- [[Code Intelligence Hub]]",
            "",
            "## Related notes",
            "",
            "- [[Intermediate Packet Index]]",
            "- [[CODE Dashboard]]",
        ]
    )
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
            frontmatter(
                {
                    "type": "hub",
                    "area": PRODUCT_CONTEXT["slug"],
                    "source": "generated",
                    **basb_frontmatter(
                        stage="organize",
                        para="resource",
                        distillation="executive",
                        actionability="now",
                    ),
                    "tags": ["research", "hub"],
                }
            ),
            "# Research Hub",
            "",
            "- [[Support Articles Hub]]",
            "- [[Wiki Pages Hub]]",
            "- [[Code Intelligence Hub]]",
            "- [[Intermediate Packet Index]]",
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
            frontmatter(
                {
                    "type": "hub",
                    "area": PRODUCT_CONTEXT["slug"],
                    "source": "generated",
                    **basb_frontmatter(
                        stage="organize",
                        para="resource",
                        distillation="executive",
                        actionability="now",
                    ),
                    "tags": ["home"],
                }
            ),
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
            "- [[CODE Dashboard]]",
            "- [[PARA Map]]",
            "- [[Output Pipeline]]",
            "- [[Product Capability Map]]",
            "- [[Support Articles Hub]]",
            "- [[Wiki Pages Hub]]",
            "- [[Code Intelligence Hub]]",
            "- [[Intermediate Packet Index]]",
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
            "- [[Archive Index]]",
        ]
    )


def build_links_by_source(external_links: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in external_links:
        for ref in entry.get("source_refs", []):
            mapping[ref].append(entry)
    return mapping


def ontology_citation(
    *,
    title: str,
    path: str = "",
    citation_uri: str = "",
    source_type: str = "",
) -> dict[str, str]:
    return {
        "title": normalize_text(title),
        "path": normalize_text(path),
        "citation_uri": normalize_text(citation_uri),
        "source_type": normalize_text(source_type),
    }


def ontology_field(value: Any, *, confidence: str, citations: list[dict[str, str]], missing_reason: str = "") -> dict[str, Any]:
    has_value = bool(value)
    return {
        "value": value,
        "confidence": confidence if has_value else "missing",
        "citations": citations[:12] if has_value else [],
        "missing_reason": "" if has_value else missing_reason,
    }


def source_record_citation(record: dict[str, Any], source_type: str) -> dict[str, str]:
    item = record["item"]
    source_uri = item.get("source_url") or item.get("relative_path") or record.get("source_ref") or ""
    return ontology_citation(
        title=record["signals"].get("title") or item.get("title") or source_uri or source_type,
        path=record.get("source_ref") or item.get("relative_path") or "",
        citation_uri=source_uri,
        source_type=source_type,
    )


def first_product_purpose(
    product_name: str,
    support_records: list[dict[str, Any]],
    wiki_records: list[dict[str, Any]],
    repo_snapshots: list[dict[str, Any]],
) -> tuple[str, list[dict[str, str]]]:
    preferred_terms = ("overview", "introduction", "readme", "getting started", "what it does", "product reference")
    for record in [*support_records, *wiki_records]:
        haystack = f"{record['signals'].get('title', '')} {record.get('source_ref', '')}".lower()
        if not any(term in haystack for term in preferred_terms):
            continue
        paragraphs = record["signals"].get("paragraphs") or []
        if paragraphs:
            source_type = "support" if record in support_records else "wiki"
            return paragraphs[0], [source_record_citation(record, source_type)]
    for snapshot in repo_snapshots:
        summary = normalize_text(str(snapshot.get("readme_summary") or ""))
        if summary:
            return summary, [
                ontology_citation(
                    title=f"Repo - {snapshot.get('name', 'repository')}",
                    path=f"repository:{snapshot.get('name', '')}",
                    citation_uri=str(snapshot.get("path") or snapshot.get("name") or ""),
                    source_type="repository",
                )
            ]
    return f"{product_name} still needs stronger README, documentation, or product profile evidence.", []


def ontology_terms_from_records(
    records: list[dict[str, Any]],
    terms: tuple[str, ...],
    *,
    limit: int = 10,
) -> tuple[list[str], list[dict[str, str]]]:
    values: list[str] = []
    citations: list[dict[str, str]] = []
    for record in records:
        text = f"{record['signals'].get('title', '')}\n{record['text']}\n{record.get('source_ref', '')}"
        if not has_any(text, terms):
            continue
        for line in [*record["signals"].get("headings", []), *record["signals"].get("bullets", []), *record["signals"].get("paragraphs", [])]:
            for token in re.findall(r"\b[A-Z][A-Za-z0-9]{2,}(?:\s+[A-Z][A-Za-z0-9]{2,})?\b", line):
                if token.casefold() in {"source", "readme", "github", "article", "overview"}:
                    continue
                if token not in values:
                    values.append(token)
                if len(values) >= limit:
                    break
            if len(values) >= limit:
                break
        source_type = "support" if record.get("source_ref", "").startswith("support") or "article" in record.get("source_ref", "") else "wiki"
        citations.append(source_record_citation(record, source_type))
        if len(values) >= limit:
            break
    return unique_lines(values, limit), citations[:8]


def build_product_ontology(
    *,
    manifest: dict[str, Any],
    support_records: list[dict[str, Any]],
    wiki_records: list[dict[str, Any]],
    repo_snapshots: list[dict[str, Any]],
    capability_rows: list[dict[str, Any]],
    code_intel: dict[str, Any],
    external_links: list[dict[str, Any]],
    docx_extracts: list[dict[str, Any]],
) -> dict[str, Any]:
    product = manifest.get("product") or {}
    product_name = str(product.get("name") or PRODUCT_CONTEXT["name"])
    product_slug = str(product.get("slug") or PRODUCT_CONTEXT["slug"])
    all_records = [*support_records, *wiki_records]
    purpose, purpose_citations = first_product_purpose(product_name, support_records, wiki_records, repo_snapshots)
    personas, persona_citations = ontology_terms_from_records(all_records, ("persona", "user", "customer", "operator", "member", "admin"))
    workflows, workflow_citations = ontology_terms_from_records(all_records, ("workflow", "flow", "journey", "process", "campaign", "challenge"))
    integrations, integration_citations = ontology_terms_from_records(all_records, EXTERNAL_SYSTEM_TERMS)
    graph = code_intel.get("graph", {})
    files = code_intel.get("files", [])
    repo_citations = [
        ontology_citation(
            title=f"Repo - {snapshot.get('name', 'repository')}",
            path=f"repository:{snapshot.get('name', '')}",
            citation_uri=str(snapshot.get("path") or snapshot.get("name") or ""),
            source_type="repository",
        )
        for snapshot in repo_snapshots
    ]
    code_citations = [
        ontology_citation(
            title=f"{item.get('repo', '')}/{item.get('relative_path', '')}",
            path=str(item.get("relative_path") or ""),
            citation_uri=f"{item.get('repo', '')}/{item.get('relative_path', '')}",
            source_type="code",
        )
        for item in files[:12]
    ]
    repositories = [
        {
            "name": snapshot.get("name"),
            "role": snapshot.get("role"),
            "branch": snapshot.get("branch"),
            "readme_title": snapshot.get("readme_title"),
            "readme_summary": snapshot.get("readme_summary"),
            "top_dirs": snapshot.get("top_dirs", [])[:12],
            "key_files": snapshot.get("key_files", [])[:12],
        }
        for snapshot in repo_snapshots
    ]
    capabilities = [
        {
            "title": row["title"],
            "support_count": row["support_count"],
            "wiki_count": row["wiki_count"],
            "repositories": row["repos"],
            "code_count": row["code_count"],
        }
        for row in capability_rows
    ]
    services = unique_lines(
        [
            name
            for snapshot in repo_snapshots
            for name in [*snapshot.get("monorepo_services", []), *snapshot.get("monorepo_apps", [])]
        ],
        20,
    )
    apis = [edge.get("to", "") for edge in graph.get("routes", [])[:80] if edge.get("to")]
    data_entities = [edge.get("to", "") for edge in graph.get("schemas", [])[:80] if edge.get("to")]
    test_map = [edge.get("to", "") for edge in graph.get("tests", [])[:80] if edge.get("to")]
    deployment_terms = ("deploy", "deployment", "staging", "preview", "production", "kubernetes", "helm", "terraform", "cdk")
    environments = unique_lines(
        [
            item.get("relative_path", "")
            for item in files
            if has_any(f"{item.get('relative_path', '')} {' '.join(item.get('dependencies', []))}", deployment_terms)
        ],
        20,
    )
    known_bugs = unique_lines(
        [
            source_record_citation(record, "support")["title"]
            for record in all_records
            if has_any(f"{record['signals'].get('title', '')}\n{record['text']}", ("bug", "failure", "error", "regression", "ticket"))
        ],
        12,
    )
    source_citations = unique_lines(
        [json.dumps(item, sort_keys=True) for item in [*purpose_citations, *repo_citations, *code_citations, *persona_citations, *workflow_citations, *integration_citations]],
        30,
    )
    parsed_citations = [json.loads(item) for item in source_citations]
    fields = {
        "product_purpose": ontology_field(purpose, confidence="medium" if purpose_citations else "low", citations=purpose_citations, missing_reason="No product overview or README summary was found."),
        "personas": ontology_field(personas, confidence="medium", citations=persona_citations, missing_reason="No user/persona evidence was found."),
        "capabilities": ontology_field(capabilities, confidence="high" if capabilities else "missing", citations=repo_citations, missing_reason="No capability profile rows were generated."),
        "workflows": ontology_field(workflows, confidence="medium", citations=workflow_citations, missing_reason="No workflow evidence was found."),
        "repositories": ontology_field(repositories, confidence="high" if repositories else "missing", citations=repo_citations, missing_reason="No repositories were indexed."),
        "services": ontology_field(services, confidence="medium", citations=repo_citations, missing_reason="No services or apps were detected."),
        "apis": ontology_field(apis, confidence="medium", citations=code_citations, missing_reason="No routes or API contracts were detected."),
        "data_entities": ontology_field(data_entities, confidence="medium", citations=code_citations, missing_reason="No schemas or data entities were detected."),
        "integrations": ontology_field(integrations, confidence="medium", citations=integration_citations, missing_reason="No integration evidence was found."),
        "environments": ontology_field(environments, confidence="medium", citations=code_citations, missing_reason="No deployment or environment evidence was detected."),
        "test_map": ontology_field(test_map, confidence="medium", citations=code_citations, missing_reason="No test anchors were detected."),
        "known_bugs": ontology_field(known_bugs, confidence="medium", citations=parsed_citations, missing_reason="No bug/support evidence was detected."),
    }
    ci_cd_profile = {
        "summary": code_intel.get("summary", {}),
        "repo_summaries": code_intel.get("repos", []),
        "test_anchor_count": len(test_map),
        "route_count": len(apis),
        "schema_count": len(data_entities),
        "deployment_signals": environments,
    }
    return {
        "schema_version": 1,
        "source": "codex-second-brain-starter-kit",
        "generated_at": DATE,
        "product": {"name": product_name, "slug": product_slug},
        "product_purpose": purpose,
        "personas": personas,
        "capabilities": [row["title"] for row in capability_rows],
        "workflows": workflows,
        "repositories": [snapshot.get("name") for snapshot in repo_snapshots],
        "repository_details": repositories,
        "services": services,
        "apis": apis,
        "events_jobs": unique_lines([item.get("relative_path", "") for item in files if has_any(item.get("relative_path", ""), ("job", "worker", "cron", "queue"))], 20),
        "data_entities": data_entities,
        "integrations": integrations,
        "environments": environments,
        "ci_cd_profile": ci_cd_profile,
        "test_map": test_map,
        "known_bugs": known_bugs,
        "feature_areas": [row["title"] for row in capability_rows],
        "source_inventory": {
            "support_notes": len(support_records),
            "wiki_notes": len(wiki_records),
            "repositories": [snapshot.get("name") for snapshot in repo_snapshots],
            "docx_extracts": len(docx_extracts),
            "external_links": len(external_links),
        },
        "fields": fields,
        "source_citations": parsed_citations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild a product second brain with durable source and code notes.")
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    profile = load_product_profile(manifest)
    configure_runtime(manifest, profile)
    paths = manifest_paths(manifest)
    repo_roots = repo_lookup(manifest)
    semantic_config = profile["semantic_clustering"]
    semantic_clustering.require_openai_or_fixture()
    code_intel = code_intelligence.analyze_repositories(repo_roots, profile)
    write_json(paths.json_dir / "code_intelligence.json", code_intel)
    write_json(paths.json_dir / "code_graph.json", code_intel.get("graph", {}))
    code_intel_by_path = {
        (item["repo"], item["relative_path"]): item
        for item in code_intel.get("files", [])
    }
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
    code_maps_dir = code_dir / "Maps"
    code_graphs_dir = code_dir / "Graphs"
    intermediate_packet_dir = paths.vault / "40 Research" / "Intermediate Packets"
    output_candidate_dir = paths.vault / "30 Initiatives" / "Output Candidates"
    review_dir = paths.vault / "70 Journal" / "Reviews"
    stale_archive_dir = paths.vault / "90 Archive" / "Stale Sources"
    capability_dir = paths.vault / "20 Product" / "Capabilities"

    clear_markdown_dir(support_dir)
    clear_markdown_dir(wiki_dir)
    clear_markdown_dir(repo_notes_dir)
    clear_markdown_dir(code_reference_dir)
    clear_generated_markdown_dir(code_maps_dir)
    clear_generated_markdown_dir(code_graphs_dir)
    clear_generated_markdown_dir(intermediate_packet_dir)
    clear_generated_markdown_dir(output_candidate_dir)
    clear_generated_markdown_dir(review_dir)
    clear_generated_markdown_dir(stale_archive_dir)
    clear_markdown_dir(capability_dir)

    ensure_dir(support_dir)
    ensure_dir(wiki_dir)
    ensure_dir(repo_notes_dir)
    ensure_dir(code_reference_dir)
    ensure_dir(code_maps_dir)
    ensure_dir(code_graphs_dir)
    ensure_dir(intermediate_packet_dir)
    ensure_dir(output_candidate_dir)
    ensure_dir(review_dir)
    ensure_dir(stale_archive_dir)
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
                code_file=code_intel_by_path.get(key),
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
        record["code_reference_links"] = code_reference_links
        record["quality"] = capture_quality_score(
            signals=record["signals"],
            link_records=links_by_source.get(record["source_ref"], []),
            code_reference_links=code_reference_links,
            capabilities=record["capabilities"],
            conflicts=[item["message"] for item in record["conflicts"]],
        )
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
        record["code_reference_links"] = code_reference_links
        record["quality"] = capture_quality_score(
            signals=record["signals"],
            link_records=links_by_source.get(record["source_ref"], []),
            code_reference_links=code_reference_links,
            capabilities=record["capabilities"],
            conflicts=[item["message"] for item in record["conflicts"]],
        )
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

    semantic_cards = build_semantic_evidence_cards(
        support_records=support_records,
        wiki_records=wiki_records,
        code_reference_registry=code_reference_registry,
        code_reference_stems=code_reference_stems,
        code_intel_by_path=code_intel_by_path,
    )
    semantic_result = semantic_clustering.cluster_cards(
        semantic_cards,
        semantic_config,
        paths.json_dir / "embedding_cache.json",
    )
    write_json(paths.json_dir / "semantic_clusters.json", semantic_result)

    capability_rows: list[dict[str, Any]] = []
    packet_records: list[dict[str, Any]] = []
    packet_links: list[str] = []
    packet_write_specs: dict[str, dict[str, Any]] = {}
    support_grouped_for_hub: dict[str, list[str]] = defaultdict(list)
    for key, links in support_links_by_cap.items():
        support_grouped_for_hub[key] = sorted(links)
    all_source_records = [*support_records, *wiki_records]
    for capability in CAPABILITIES:
        cap_stem = stem_for_capability(capability["title"])
        support_links = sorted(support_links_by_cap.get(capability["key"], []))
        wiki_links = sorted(wiki_links_by_cap.get(capability["key"], []))
        repo_note_links = [note_link(stem_for_repo(repo_name)) for repo_name in capability["repos"]]
        code_hits = code_hits_by_cap.get(capability["key"], [])
        code_reference_links = [code_reference_link(hit, code_reference_stems) for hit in code_hits]
        capability_records = [
            record
            for record in all_source_records
            if capability["key"] in record["capabilities"]
        ]
        conflict_links = [
            f"{note_link(record['stem'])}: {conflict['message']}"
            for record in capability_records
            for conflict in record.get("conflicts", [])
        ]
        stale_doc_count = sum(
            1
            for record in capability_link_records.get(capability["key"], [])
            if record.get("status") == "stale-doc-reference"
        )
        evidence_score = score_packet_evidence(
            support_links=support_links,
            wiki_links=wiki_links,
            code_reference_links=code_reference_links,
            conflict_count=len(conflict_links),
            stale_doc_count=stale_doc_count,
        )
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
        packet_stem = safe_filename(f"Packet - {capability['title']}")
        packet_link = note_link(packet_stem)
        packet_record = {
            "title": capability["title"],
            "stem": packet_stem,
            "link": packet_link,
            "packet_kind": "capability",
            "support_links": support_links,
            "wiki_links": wiki_links,
            "repo_note_links": repo_note_links,
            "code_reference_links": code_reference_links,
            "conflict_links": conflict_links,
            "conflict_count": len(conflict_links),
            "stale_doc_count": stale_doc_count,
            "evidence_score": evidence_score,
        }
        packet_write_specs[packet_stem] = {
            "kind": "standard",
            "capability": capability,
            "support_links": support_links,
            "wiki_links": wiki_links,
            "repo_note_links": repo_note_links,
            "code_reference_links": code_reference_links,
            "packet_kind": "capability",
            "conflict_links": conflict_links,
            "stale_doc_count": stale_doc_count,
            "evidence_score": evidence_score,
        }
        write_generated_note(
            intermediate_packet_dir / f"{packet_stem}.md",
            build_intermediate_packet_note(
                capability=capability,
                support_links=support_links,
                wiki_links=wiki_links,
                repo_note_links=repo_note_links,
                code_reference_links=code_reference_links,
                conflict_links=conflict_links,
                stale_doc_count=stale_doc_count,
                evidence_score=evidence_score,
            ),
        )
        packet_records.append(packet_record)
        packet_links.append(packet_link)
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

    product_ontology = build_product_ontology(
        manifest=manifest,
        support_records=support_records,
        wiki_records=wiki_records,
        repo_snapshots=repo_snapshots,
        capability_rows=capability_rows,
        code_intel=code_intel,
        external_links=external_links,
        docx_extracts=docx_extracts,
    )
    write_json(paths.json_dir / "product_ontology.json", product_ontology)

    conflict_titles = {
        "documentation-drift": "Documentation Drift",
        "restricted-source": "Restricted Source",
        "code-traceability-gap": "Code Traceability Gap",
    }
    for kind, entries in sorted(conflict_entries_by_kind.items()):
        if len(entries) < 2:
            continue
        title = f"{conflict_titles.get(kind, kind.title())} Evidence Cluster"
        packet_stem = safe_filename(f"Packet - {title}")
        packet_link = note_link(packet_stem)
        evidence_score = min(10, 4 + min(6, len(entries)))
        capability = {
            "key": f"cluster-{kind}",
            "title": title,
            "description": f"Reusable packet for recurring {kind.replace('-', ' ')} signals found across the source corpus.",
        }
        packet_record = {
            "title": title,
            "stem": packet_stem,
            "link": packet_link,
            "packet_kind": "conflict-cluster",
            "conflict_kind": kind,
            "support_links": [],
            "wiki_links": [],
            "repo_note_links": [],
            "code_reference_links": [],
            "conflict_links": unique_lines(entries, 30),
            "conflict_count": len(entries),
            "stale_doc_count": len(entries) if kind == "documentation-drift" else 0,
            "evidence_score": evidence_score,
        }
        packet_write_specs[packet_stem] = {
            "kind": "standard",
            "capability": capability,
            "support_links": [],
            "wiki_links": [],
            "repo_note_links": [],
            "code_reference_links": [],
            "packet_kind": "conflict-cluster",
            "conflict_links": packet_record["conflict_links"],
            "stale_doc_count": packet_record["stale_doc_count"],
            "evidence_score": evidence_score,
        }
        write_generated_note(
            intermediate_packet_dir / f"{packet_stem}.md",
            build_intermediate_packet_note(
                capability=capability,
                support_links=[],
                wiki_links=[],
                repo_note_links=[],
                code_reference_links=[],
                packet_kind="conflict-cluster",
                conflict_links=packet_record["conflict_links"],
                stale_doc_count=packet_record["stale_doc_count"],
                evidence_score=evidence_score,
            ),
        )
        packet_records.append(packet_record)
        packet_links.append(packet_link)

    code_path_packets: list[tuple[int, tuple[str, str], dict[str, Any]]] = []
    for key, entry in code_reference_registry.items():
        support_links = unique_lines(entry["support_links"], 40)
        wiki_links = unique_lines(entry["wiki_links"], 40)
        if len(support_links) + len(wiki_links) < 2:
            continue
        score = score_packet_evidence(
            support_links=support_links,
            wiki_links=wiki_links,
            code_reference_links=[code_reference_link(entry["hit"], code_reference_stems)],
        )
        code_path_packets.append((score, key, entry))
    for score, key, entry in sorted(code_path_packets, key=lambda item: (-item[0], item[1]))[:20]:
        hit = entry["hit"]
        title = f"Code Path - {hit['repo']}/{hit['relative_path']}"
        packet_stem = safe_filename(f"Packet - {title}", limit=180)
        packet_link = note_link(packet_stem)
        support_links = unique_lines(entry["support_links"], 40)
        wiki_links = unique_lines(entry["wiki_links"], 40)
        code_reference_links = [code_reference_link(hit, code_reference_stems)]
        repo_note_links = [note_link(stem_for_repo(hit["repo"]))]
        capability = {
            "key": f"code-path-{dedupe_key(title)[:48]}",
            "title": title,
            "description": "Reusable code-path packet linking repeated product evidence to one implementation anchor.",
        }
        packet_record = {
            "title": title,
            "stem": packet_stem,
            "link": packet_link,
            "packet_kind": "code-path-cluster",
            "support_links": support_links,
            "wiki_links": wiki_links,
            "repo_note_links": repo_note_links,
            "code_reference_links": code_reference_links,
            "conflict_links": [],
            "conflict_count": 0,
            "stale_doc_count": 0,
            "evidence_score": score,
        }
        packet_write_specs[packet_stem] = {
            "kind": "standard",
            "capability": capability,
            "support_links": support_links,
            "wiki_links": wiki_links,
            "repo_note_links": repo_note_links,
            "code_reference_links": code_reference_links,
            "packet_kind": "code-path-cluster",
            "conflict_links": [],
            "stale_doc_count": 0,
            "evidence_score": score,
        }
        write_generated_note(
            intermediate_packet_dir / f"{packet_stem}.md",
            build_intermediate_packet_note(
                capability=capability,
                support_links=support_links,
                wiki_links=wiki_links,
                repo_note_links=repo_note_links,
                code_reference_links=code_reference_links,
                packet_kind="code-path-cluster",
                evidence_score=score,
            ),
        )
        packet_records.append(packet_record)
        packet_links.append(packet_link)

    for cluster in semantic_result.get("clusters", []):
        title = str(cluster.get("theme") or "Semantic Evidence Cluster")
        packet_stem = safe_filename(f"Packet - Semantic - {title}", limit=180)
        packet_link = note_link(packet_stem)
        cards = cluster.get("cards", [])
        support_links = unique_lines(
            [card.get("link", "") for card in cards if card.get("kind") == "support"],
            40,
        )
        wiki_links = unique_lines(
            [card.get("link", "") for card in cards if card.get("kind") == "wiki"],
            40,
        )
        code_reference_links = unique_lines(
            [link for card in cards for link in card.get("code_reference_links", [])],
            60,
        )
        evidence_score = int(cluster.get("evidence_score", 0) or 0)
        packet_record = {
            "title": title,
            "stem": packet_stem,
            "link": packet_link,
            "packet_kind": "semantic-cluster",
            "support_links": support_links,
            "wiki_links": wiki_links,
            "repo_note_links": [],
            "code_reference_links": code_reference_links,
            "conflict_links": [],
            "conflict_count": 0,
            "stale_doc_count": 0,
            "semantic_cluster_score": cluster.get("similarity_score", 0),
            "evidence_score": evidence_score,
        }
        packet_write_specs[packet_stem] = {
            "kind": "semantic",
            "cluster": cluster,
        }
        write_generated_note(
            intermediate_packet_dir / f"{packet_stem}.md",
            build_semantic_packet_note(cluster),
        )
        packet_records.append(packet_record)
        packet_links.append(packet_link)

    output_candidate_records: list[dict[str, Any]] = []
    output_links_by_packet: dict[str, list[str]] = defaultdict(list)
    for packet in select_output_candidates(packet_records):
        output_kind = infer_output_kind(packet)
        output_stem = stem_for_output_candidate(packet["title"])
        output_link = note_link(output_stem)
        write_generated_note(output_candidate_dir / f"{output_stem}.md", build_output_candidate_note(packet))
        output_links_by_packet[packet["link"]].append(output_link)
        output_candidate_records.append(
            {
                "title": packet["title"],
                "stem": output_stem,
                "link": output_link,
                "output_kind": output_kind,
                "source_packet": packet["link"],
                "evidence_score": packet.get("evidence_score", 0),
            }
        )

    for packet in packet_records:
        spec = packet_write_specs.get(packet["stem"])
        if not spec:
            continue
        write_generated_note(
            intermediate_packet_dir / f"{packet['stem']}.md",
            build_packet_note_from_spec(spec, unique_lines(output_links_by_packet.get(packet["link"], []), 12)),
        )

    stale_doc_refs = [entry for entry in external_links if entry.get("status") == "stale-doc-reference"]
    archive_records_written = 0
    if stale_doc_refs:
        write_note(stale_archive_dir / f"Stale Sources - {DATE}.md", build_stale_sources_archive_note(stale_doc_refs))
        archive_records_written = 1
    write_note(
        review_dir / f"Weekly Review - {DATE}.md",
        build_weekly_review_note(packet_records, output_candidate_records, stale_doc_refs, conflict_entries_by_kind),
    )

    write_note(support_dir / "Support Articles Hub.md", build_support_articles_hub(support_grouped_for_hub))
    write_note(wiki_dir / "Wiki Pages Hub.md", build_wiki_pages_hub({key: sorted(value) for key, value in section_grouped.items()}))
    write_note(code_dir / "Code Intelligence Hub.md", build_code_intelligence_hub(repo_links, [row["link"] for row in capability_rows]))
    write_note(code_dir / "Code Reference Index.md", build_code_reference_index({key: sorted(value) for key, value in code_reference_index.items()}))
    write_note(code_maps_dir / "Route Map.md", build_route_map(code_intel))
    write_note(code_maps_dir / "Schema And Data Model Map.md", build_schema_map(code_intel))
    write_note(code_graphs_dir / "Call Graph Map.md", build_call_graph_map(code_intel))
    write_note(code_graphs_dir / "Dependency Graph Map.md", build_dependency_graph_map(code_intel))
    write_note(code_maps_dir / "Test Coverage Map.md", build_test_coverage_map(code_intel))
    write_note(code_maps_dir / "Ownership And Churn Map.md", build_ownership_churn_map(code_intel))
    write_note(intermediate_packet_dir / "Intermediate Packet Index.md", build_intermediate_packet_index(packet_links))
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
                "intermediate_packets": len(packet_records),
                "output_candidates": len(output_candidate_records),
                "archive_records": archive_records_written,
                "repo_notes": len(repo_snapshots),
                "product_ontology": str(paths.json_dir / "product_ontology.json"),
                "code_intelligence": code_intel.get("summary", {}),
                "semantic_clusters": len(semantic_result.get("clusters", [])),
                "semantic_stats": semantic_result.get("stats", {}),
                "vault": str(paths.vault),
                "vault_sanitizer": sanitize_summary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
