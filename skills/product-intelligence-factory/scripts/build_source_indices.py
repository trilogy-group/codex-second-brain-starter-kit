#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import re
import ssl
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generation_performance
import generation_progress
import rate_limits
import source_index_cache


DATE = date.today().isoformat()
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
SUPPORT_ARTICLE_URL_RE = re.compile(r"/article/(\d{3,8})(?:-[^/?#]*)?/?$", re.IGNORECASE)
SUPPORT_ARTICLE_FILENAME_RE = re.compile(r"(?:^|[_-])(\d{3,8})-article$", re.IGNORECASE)

PLACEHOLDER_PARTS = (
    "{",
    "}",
    "<",
    ">",
    "${",
    "yourhub",
    "yourdomain",
    "yourcompany",
    "example.com",
    "window.location",
    "author.email",
    "url.com",
)
PLACEHOLDER_HOST_LABELS = {"hubname", "yourhub", "yourdomain", "yourcompany", "example"}
TRAILING_CHARS = ".,;:)]}`\"'"
USER_AGENT = "ProductIntelligenceFactory/1.0 (+https://github.com/trilogy-group/codex-second-brain-starter-kit)"
SOURCE_EXTRACT_CACHE_SCHEMA_VERSION = 1
SOURCE_EXTRACT_CACHE_LOCK = threading.Lock()
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_BACKOFF_SECONDS = 0.25
RETRYABLE_URL_ERROR_MARKERS = (
    "temporary failure in name resolution",
    "name or service not known",
    "nodename nor servname",
    "try again",
    "timed out",
    "timeout",
    "connection reset",
    "network is unreachable",
    "temporarily unavailable",
)
RETRYABLE_URL_ERRNOS = {-3, -2, 54, 60, 61, 101, 104, 110, 111}
COMMENT_AUTH_PROMPTS = (
    "please sign in to comment",
    "sign in to comment",
    "please log in to comment",
    "log in to comment",
    "please login to comment",
    "login to comment",
)


def default_ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore[import-not-found]

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


@dataclass
class Paths:
    workspace: Path
    vault: Path
    corpus: Path
    mirror: Path
    docx_extract: Path
    repos_root: Path
    links_dir: Path
    json_dir: Path


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"Manifest root must be a mapping: {path}")
    return data


def load_generation_performance(manifest: dict[str, Any]) -> dict[str, Any]:
    profile_path = (manifest.get("profile") or {}).get("intelligence_path")
    if not profile_path:
        return generation_performance.default_generation_config({})
    path = Path(str(profile_path)).expanduser()
    if not path.exists():
        return generation_performance.default_generation_config({})
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return generation_performance.default_generation_config(data if isinstance(data, dict) else {})


def load_rate_limit_config(manifest: dict[str, Any]) -> dict[str, Any]:
    profile_path = (manifest.get("profile") or {}).get("intelligence_path")
    if not profile_path:
        return generation_performance.default_rate_limit_config({})
    path = Path(str(profile_path)).expanduser()
    if not path.exists():
        return generation_performance.default_rate_limit_config({})
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return generation_performance.default_rate_limit_config(data if isinstance(data, dict) else {})


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def product_settings(manifest: dict[str, Any], generation_config: dict[str, Any] | None = None) -> dict[str, Any]:
    product = manifest.get("product") or {}
    sources = manifest.get("sources") or {}
    generation_config = generation_config or generation_performance.default_generation_config({})
    return {
        "product_name": str(product.get("name", "Product")),
        "product_slug": str(product.get("slug", "product")),
        "support_article_url_template": str(sources.get("support_article_url_template", "")),
        "source_extract_workers": generation_config["source_extract_workers"],
        "source_fetch_workers": generation_config["source_fetch_workers"],
        "stale_doc_hosts": {
            str(host).lower()
            for host in (sources.get("stale_doc_hosts") or [])
            if str(host).strip()
        },
    }


def support_source_url(article_id: str, settings: dict[str, Any]) -> str:
    template = str(settings.get("support_article_url_template", ""))
    if not article_id.isdigit() or not template:
        return ""
    return template.format(article_id=article_id)


def repo_path_by_role(manifest: dict[str, Any], role: str) -> Path | None:
    for item in manifest.get("repositories", {}).get("items", []):
        if item.get("role") == role and item.get("local_path"):
            return Path(str(item["local_path"])).expanduser()
    return None


def manifest_paths(data: dict[str, Any]) -> Paths:
    product = data["product"]
    sources = data["sources"]
    repos = data["repositories"]
    mirror = Path(str(sources["mirror_path"])).expanduser()
    return Paths(
        workspace=Path(str(product["workspace_path"])).expanduser(),
        vault=Path(str(product["vault_path"])).expanduser(),
        corpus=Path(str(sources["corpus_path"])).expanduser(),
        mirror=mirror,
        docx_extract=Path(str(sources["docx_extract_path"])).expanduser(),
        repos_root=Path(str(repos["local_clone_root"])).expanduser(),
        links_dir=mirror / "external-pages",
        json_dir=mirror / "inventories",
    )


def title_from_text(text: str, fallback: str) -> str:
    match = TITLE_RE.search(text)
    if match:
        return WHITESPACE_RE.sub(" ", match.group(1)).strip()
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:160]
    return fallback


def sanitize_url(raw_url: str) -> str | None:
    url = raw_url.strip().rstrip(TRAILING_CHARS)
    if not url.startswith(("http://", "https://")):
        return None
    if any(part in url.lower() for part in PLACEHOLDER_PARTS):
        return None
    if " " in url or "\n" in url or "`" in url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.netloc or "." not in parsed.netloc:
        return None
    host_labels = set((parsed.hostname or parsed.netloc).lower().split("."))
    if host_labels.intersection(PLACEHOLDER_HOST_LABELS):
        return None
    if parsed.netloc.endswith(".internal"):
        return None
    return url


def support_article_id_from_path(path: Path) -> str:
    match = SUPPORT_ARTICLE_FILENAME_RE.search(path.stem)
    return match.group(1) if match else ""


def normalize_known_support_url(url: str) -> str:
    parsed = urlparse(url)
    article_match = SUPPORT_ARTICLE_URL_RE.search(parsed.path)
    if not article_match:
        return url.split("#", 1)[0]
    article_id = article_match.group(1)
    return f"{parsed.scheme}://{parsed.netloc}/article/{article_id}"


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value[:120] or "item"


def empty_source_extract_cache() -> dict[str, Any]:
    return {
        "schema_version": SOURCE_EXTRACT_CACHE_SCHEMA_VERSION,
        "entries": {},
        "stats": {"hits": 0, "misses": 0, "force_misses": 0, "invalidations": 0},
    }


def reset_source_extract_cache_stats(cache: dict[str, Any]) -> None:
    cache["stats"] = {"hits": 0, "misses": 0, "force_misses": 0, "invalidations": 0}


def load_source_extract_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_source_extract_cache()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid source extract cache JSON at {path}; delete it or rerun with --force.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SOURCE_EXTRACT_CACHE_SCHEMA_VERSION:
        raise SystemExit(
            f"Unsupported source extract cache schema at {path}; "
            f"expected schema_version {SOURCE_EXTRACT_CACHE_SCHEMA_VERSION}."
        )
    if not isinstance(payload.get("entries"), dict):
        payload["entries"] = {}
    if not isinstance(payload.get("stats"), dict):
        reset_source_extract_cache_stats(payload)
    payload["stats"].setdefault("hits", 0)
    payload["stats"].setdefault("misses", 0)
    payload["stats"].setdefault("force_misses", 0)
    payload["stats"].setdefault("invalidations", 0)
    return payload


def write_source_extract_cache(path: Path, cache: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    cache["schema_version"] = SOURCE_EXTRACT_CACHE_SCHEMA_VERSION
    cache.setdefault("entries", {})
    cache.setdefault("stats", {})
    path.write_text(json.dumps(cache, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def source_file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def source_extract_input_hash(path: Path, settings_fingerprint: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "path": path.as_posix(),
                "content_sha256": source_file_hash(path),
                "settings": settings_fingerprint,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _source_extract_stage(cache: dict[str, Any], namespace: str) -> dict[str, Any]:
    entries = cache.setdefault("entries", {})
    stage = entries.setdefault(namespace, {})
    if not isinstance(stage, dict):
        raise SystemExit(f"Invalid source extract cache stage `{namespace}`; expected a mapping.")
    return stage


def cached_source_extract(
    cache: dict[str, Any] | None,
    namespace: str,
    key: str,
    path: Path,
    settings_fingerprint: dict[str, Any],
    builder: Any,
    *,
    force: bool = False,
) -> Any:
    if cache is None:
        return builder()
    input_hash = source_extract_input_hash(path, settings_fingerprint)
    with SOURCE_EXTRACT_CACHE_LOCK:
        stage = _source_extract_stage(cache, namespace)
        entry = stage.get(key)
        if not force and isinstance(entry, dict) and entry.get("input_hash") == input_hash and "value" in entry:
            cache["stats"]["hits"] = int(cache["stats"].get("hits", 0)) + 1
            return entry["value"]
        if force:
            cache["stats"]["force_misses"] = int(cache["stats"].get("force_misses", 0)) + 1
        elif isinstance(entry, dict):
            cache["stats"]["invalidations"] = int(cache["stats"].get("invalidations", 0)) + 1
    value = builder()
    with SOURCE_EXTRACT_CACHE_LOCK:
        stage = _source_extract_stage(cache, namespace)
        stage[key] = {"input_hash": input_hash, "value": value}
        cache["stats"]["misses"] = int(cache["stats"].get("misses", 0)) + 1
    return value


def _source_extract_workers(settings: dict[str, Any] | None = None, workers: int | None = None) -> int:
    if workers is not None:
        return max(1, int(workers))
    if settings is None:
        return 1
    return max(1, int(settings.get("source_extract_workers", 1)))


def _run_ordered_source_tasks(items: list[Path], worker_count: int, task: Any) -> list[Any]:
    if not items:
        return []
    if worker_count <= 1:
        return [task(item) for item in items]
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="basb-source-extract") as executor:
        return list(executor.map(task, items))


def extract_docx_files(
    paths: Paths,
    *,
    source_cache: dict[str, Any] | None = None,
    force: bool = False,
    workers: int = 1,
) -> list[dict[str, Any]]:
    ensure_dir(paths.docx_extract)
    docx_paths = sorted(paths.corpus.rglob("*.docx"))

    def extract_one(docx_path: Path) -> dict[str, Any]:
        rel = docx_path.relative_to(paths.corpus)
        out_path = paths.docx_extract / rel.with_suffix(".txt")
        settings_fingerprint = {"source_type": "docx", "relative_path": str(rel)}

        def build() -> dict[str, Any]:
            ensure_dir(out_path.parent)
            try:
                completed = subprocess.run(
                    ["textutil", "-convert", "txt", "-stdout", str(docx_path)],
                    check=True,
                    capture_output=True,
                )
                text = completed.stdout.decode("utf-8", errors="ignore")
                out_path.write_text(text, encoding="utf-8")
                return {
                    "path": str(docx_path),
                    "relative_path": str(rel),
                    "extract_path": str(out_path),
                    "title": title_from_text(text, docx_path.stem),
                    "char_count": len(text),
                }
            except subprocess.CalledProcessError as exc:
                return {
                    "path": str(docx_path),
                    "relative_path": str(rel),
                    "extract_path": str(out_path),
                    "title": docx_path.stem,
                    "error": exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else "textutil failed",
                }

        return cached_source_extract(
            source_cache,
            "docx_extracts",
            str(rel),
            docx_path,
            settings_fingerprint,
            build,
            force=force,
        )

    return _run_ordered_source_tasks(docx_paths, max(1, int(workers)), extract_one)


def collect_support_articles(
    paths: Paths,
    settings: dict[str, Any],
    *,
    source_cache: dict[str, Any] | None = None,
    force: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    md_paths = sorted(paths.corpus.rglob("*.md"))

    def collect_one(md_path: Path) -> dict[str, Any]:
        rel = md_path.relative_to(paths.corpus)
        settings_fingerprint = {
            "source_type": "support-markdown",
            "support_article_url_template": settings.get("support_article_url_template", ""),
            "relative_path": str(rel),
        }

        def build() -> dict[str, Any]:
            text = md_path.read_text(errors="ignore")
            article_id = support_article_id_from_path(rel)
            source_url = support_source_url(article_id, settings)
            title = title_from_text(text, md_path.stem)
            urls = sorted({url for url in (sanitize_url(item) for item in URL_RE.findall(text)) if url})
            return {
                "article": {
                    "article_id": article_id if article_id.isdigit() else "",
                    "title": title,
                    "relative_path": str(rel),
                    "source_url": source_url,
                    "link_count": len(urls),
                    "category": "support-article" if article_id or rel.name.endswith("-article.md") else "reference-doc",
                },
                "urls": urls,
            }

        return cached_source_extract(
            source_cache,
            "support_markdown",
            str(rel),
            md_path,
            settings_fingerprint,
            build,
            force=force,
        )

    articles: list[dict[str, Any]] = []
    links: dict[str, set[str]] = defaultdict(set)
    for result in _run_ordered_source_tasks(md_paths, _source_extract_workers(settings), collect_one):
        article = result["article"]
        articles.append(article)
        for url in result["urls"]:
            links[url].add(article["relative_path"])
    return articles, links


def collect_wiki_pages(
    paths: Paths,
    manifest: dict[str, Any],
    *,
    source_cache: dict[str, Any] | None = None,
    force: bool = False,
    settings: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    wiki_root = repo_path_by_role(manifest, "engineering-wiki")
    if wiki_root is None or not wiki_root.exists():
        return [], {}
    md_paths = sorted(wiki_root.rglob("*.md"))

    def collect_one(md_path: Path) -> dict[str, Any]:
        rel = md_path.relative_to(wiki_root)
        settings_fingerprint = {"source_type": "wiki-markdown", "relative_path": str(rel)}

        def build() -> dict[str, Any]:
            text = md_path.read_text(errors="ignore")
            urls = sorted({url for url in (sanitize_url(item) for item in URL_RE.findall(text)) if url})
            return {
                "page": {
                    "title": title_from_text(text, md_path.stem),
                    "relative_path": str(rel),
                    "section": rel.parts[0] if len(rel.parts) > 1 else "root",
                    "link_count": len(urls),
                },
                "urls": urls,
            }

        return cached_source_extract(
            source_cache,
            "wiki_markdown",
            str(rel),
            md_path,
            settings_fingerprint,
            build,
            force=force,
        )

    pages: list[dict[str, Any]] = []
    links: dict[str, set[str]] = defaultdict(set)
    for result in _run_ordered_source_tasks(md_paths, _source_extract_workers(settings), collect_one):
        page = result["page"]
        pages.append(page)
        for url in result["urls"]:
            links[url].add(f"wiki/{page['relative_path']}")
    return pages, links


def summarize_readme(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "", ""
    text = path.read_text(errors="ignore")
    title = title_from_text(text, path.parent.name)
    summary = ""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            summary = line[:240]
            break
    return title, summary


def collect_repo_snapshots(data: dict[str, Any], paths: Paths) -> list[dict[str, Any]]:
    del paths
    snapshots: list[dict[str, Any]] = []
    for item in data["repositories"]["items"]:
        repo_path = Path(str(item["local_path"])).expanduser()
        if not repo_path.exists():
            snapshots.append(
                {
                    "name": item["name"],
                    "role": item["role"],
                    "branch": item["default_branch"],
                    "path": str(repo_path),
                    "path_exists": False,
                    "readme_title": "",
                    "readme_summary": "",
                    "top_dirs": [],
                    "key_files": [],
                    "monorepo_apps": [],
                    "monorepo_services": [],
                }
            )
            continue
        readme_title, readme_summary = summarize_readme(repo_path / "README.md")
        top_dirs = sorted([entry.name for entry in repo_path.iterdir() if entry.is_dir() and not entry.name.startswith(".")])[:20]
        key_files = [
            name
            for name in ["README.md", "package.json", "Gemfile", "Podfile", "DockerFile", "docker-compose.yml"]
            if (repo_path / name).exists()
        ]
        monorepo_apps = []
        monorepo_services = []
        if (repo_path / "apps").exists():
            monorepo_apps = sorted([entry.name for entry in (repo_path / "apps").iterdir() if entry.is_dir()])[:50]
        if (repo_path / "services").exists():
            monorepo_services = sorted([entry.name for entry in (repo_path / "services").iterdir() if entry.is_dir()])[:80]
        snapshots.append(
            {
                "name": item["name"],
                "role": item["role"],
                "branch": item["default_branch"],
                "path": str(repo_path),
                "path_exists": True,
                "readme_title": readme_title,
                "readme_summary": readme_summary,
                "top_dirs": top_dirs,
                "key_files": key_files,
                "monorepo_apps": monorepo_apps,
                "monorepo_services": monorepo_services,
            }
        )
    return snapshots


def html_to_text(raw_html: str) -> str:
    text = SCRIPT_STYLE_RE.sub(" ", raw_html)
    text = TAG_RE.sub(" ", text)
    text = unescape(text)
    return WHITESPACE_RE.sub(" ", text).strip()


def is_retryable_url_error(exc: URLError) -> bool:
    reason = exc.reason
    if isinstance(reason, (TimeoutError, ConnectionResetError, ConnectionAbortedError)):
        return True
    errno = getattr(reason, "errno", None)
    if isinstance(errno, int) and errno in RETRYABLE_URL_ERRNOS:
        return True
    reason_text = str(reason).lower()
    return any(marker in reason_text for marker in RETRYABLE_URL_ERROR_MARKERS)


def is_likely_auth_gated_text(body_text: str) -> bool:
    inspected = body_text.lower()[:2000]
    for prompt in COMMENT_AUTH_PROMPTS:
        inspected = inspected.replace(prompt, " ")
    inspected = WHITESPACE_RE.sub(" ", inspected).strip()
    if inspected in {"sign in", "log in", "login"}:
        return True
    if re.search(r"\b(access denied|unauthorized|forbidden)\b", inspected):
        return True
    if re.search(r"\b(?:sign in|log in|login)\b.{0,120}\b(?:to continue|to access|to view|required)\b", inspected):
        return True
    if re.search(r"\b(?:sign in|log in|login)\b", inspected) and any(
        marker in inspected for marker in ("password", "single sign-on", "sso", "authentication required")
    ):
        return True
    return False


def is_legacy_doc_host(domain: str, settings: dict[str, Any]) -> bool:
    return domain in settings.get("stale_doc_hosts", set())


def classify_special_url(url: str, settings: dict[str, Any]) -> str | None:
    parsed = urlparse(url)
    domain = (parsed.hostname or parsed.netloc).lower()
    if domain.startswith("docs.google.com") or domain.startswith("drive.google.com"):
        return "needs-google-drive"
    if is_legacy_doc_host(domain, settings):
        return "stale-doc-reference"
    if "confluence." in domain or "zendesk.com" in domain:
        return "likely-auth-gated"
    return None


def fetch_url(url: str, source_refs: list[str], links_dir: Path, settings: dict[str, Any]) -> dict[str, Any]:
    special = classify_special_url(url, settings)
    parsed_url = urlparse(url)
    domain = (parsed_url.hostname or parsed_url.netloc).lower()
    record: dict[str, Any] = {
        "url": url,
        "domain": domain,
        "source_refs": source_refs,
        "status": special or "pending",
    }
    if special in {"needs-google-drive", "stale-doc-reference"}:
        return record
    limiter = settings.get("rate_limiter")
    if limiter is not None:
        waited = limiter.acquire_source_fetch(
            host=domain,
            stage="source_fetch",
            worker_count=int(settings.get("source_fetch_workers", 40)),
        )
        if waited:
            record["rate_limit_wait_seconds"] = round(waited, 4)

    request_headers = {"User-Agent": USER_AGENT}
    cached_headers = settings.get("cached_response_headers")
    if isinstance(cached_headers, dict):
        headers_for_url = cached_headers.get(url)
        if isinstance(headers_for_url, dict):
            if headers_for_url.get("etag"):
                request_headers["If-None-Match"] = str(headers_for_url["etag"])
            if headers_for_url.get("last_modified"):
                request_headers["If-Modified-Since"] = str(headers_for_url["last_modified"])
    request = Request(url, headers=request_headers)
    for attempt in range(1, FETCH_RETRY_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=8, context=default_ssl_context()) as response:
                status_code = getattr(response, "status", response.getcode())
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type", "")
                raw_bytes = response.read(512_000)
            record["retry_count"] = attempt
            break
        except HTTPError as exc:
            if exc.code == 304:
                record["status"] = "not-modified"
                record["retry_count"] = attempt
                return record
            provider_error = rate_limits.provider_rate_limit_from_http_error(exc)
            if provider_error is not None and limiter is not None:
                limiter.recorder.record(
                    stage="source_fetch",
                    event="provider_rate_limit",
                    worker_count=int(settings.get("source_fetch_workers", 40)),
                    recommended_knob="source_fetch_workers",
                    retry_after_seconds=provider_error.retry_after_seconds,
                    http_status=exc.code,
                )
            record["http_status"] = exc.code
            record["status"] = "auth-gated" if exc.code in {401, 403} else "blocked"
            record["error"] = str(exc)
            return record
        except URLError as exc:
            if attempt < FETCH_RETRY_ATTEMPTS and is_retryable_url_error(exc):
                time.sleep(FETCH_RETRY_BACKOFF_SECONDS * attempt)
                continue
            record["status"] = "transient-fetch-error"
            record["transient_error"] = True
            record["retry_count"] = attempt
            record["error"] = str(exc.reason)
            return record

    try:
        record["http_status"] = status_code
        record["final_url"] = final_url
        record["content_type"] = content_type
        record["etag"] = response.headers.get("ETag") if "response" in locals() else None
        record["last_modified"] = response.headers.get("Last-Modified") if "response" in locals() else None
        parsed = urlparse(final_url)
        record["final_domain"] = (parsed.hostname or parsed.netloc).lower()

        if status_code >= 400:
            record["status"] = "blocked"
            return record

        text = raw_bytes.decode("utf-8", errors="ignore")
        if "text/html" in content_type:
            title_match = HTML_TITLE_RE.search(text)
            body_text = html_to_text(text)
            record["title"] = unescape(title_match.group(1)).strip() if title_match else url
        else:
            body_text = text.strip()
            record["title"] = url

        if not body_text:
            record["status"] = "binary-or-empty"
            return record

        if is_likely_auth_gated_text(body_text):
            record["status"] = "auth-gated"
            return record

        ensure_dir(links_dir / record["final_domain"])
        slug = slugify(parsed.path or parsed.netloc)
        mirror_file = links_dir / record["final_domain"] / f"{slug}.md"
        mirror_file.write_text(
            "\n".join(
                [
                    "---",
                    f'url: "{url}"',
                    f'final_url: "{final_url}"',
                    f'domain: "{record["final_domain"]}"',
                    f'http_status: {status_code}',
                    f'content_type: "{content_type}"',
                    f'title: "{record["title"].replace(chr(34), chr(39))}"',
                    "---",
                    "",
                    f"# {record['title']}",
                    "",
                    f"- URL: {url}",
                    f"- Final URL: {final_url}",
                    f"- HTTP status: {status_code}",
                    "",
                    body_text[:20000],
                    "",
                ]
            )
        )
        record["status"] = "mirrored"
        record["mirror_path"] = str(mirror_file)
        return record
    except Exception as exc:  # noqa: BLE001
        record["status"] = "blocked"
        record["error"] = str(exc)
        return record


def build_link_inventory(
    source_links: dict[str, set[str]],
    paths: Paths,
    settings: dict[str, Any],
    *,
    known_local_support_urls: set[str] | None = None,
    force: bool = False,
    progress_callback: Any | None = None,
) -> list[dict[str, Any]]:
    ensure_dir(paths.links_dir)
    results: list[dict[str, Any]] = []
    local_urls = {normalize_known_support_url(url) for url in (known_local_support_urls or set())}
    local_records: list[dict[str, Any]] = []
    remote_links: dict[str, set[str]] = {}
    source_cache = settings.get("source_index_cache")
    settings_fingerprint = {
        "support_article_url_template": settings.get("support_article_url_template", ""),
        "legacy_doc_hosts": sorted(settings.get("legacy_doc_hosts", [])),
    }
    cached_response_headers: dict[str, dict[str, str]] = {}
    for url, refs in sorted(source_links.items()):
        if normalize_known_support_url(url) in local_urls:
            record = {
                "url": url,
                "domain": (urlparse(url).hostname or urlparse(url).netloc).lower(),
                "source_refs": sorted(refs),
                "status": "local-support-evidence",
            }
            local_records.append(record)
            if isinstance(source_cache, dict):
                source_index_cache.store(
                    source_cache,
                    url,
                    source_index_cache.input_hash(url, sorted(refs), settings_fingerprint),
                    record,
                )
        else:
            cache_hash = source_index_cache.input_hash(url, sorted(refs), settings_fingerprint)
            cached = (
                source_index_cache.lookup(source_cache, url, cache_hash)
                if isinstance(source_cache, dict) and not force
                else None
            )
            if cached is not None:
                results.append(cached)
                continue
            if isinstance(source_cache, dict) and not force:
                cached_entry = source_cache.get("entries", {}).get(url)
                record = cached_entry.get("record") if isinstance(cached_entry, dict) else None
                if isinstance(record, dict):
                    cached_response_headers[url] = {
                        key: str(record[key])
                        for key in ("etag", "last_modified")
                        if record.get(key)
                    }
            remote_links[url] = refs
    settings["cached_response_headers"] = cached_response_headers
    source_fetch_workers = int(settings.get("source_fetch_workers", 40))
    completed_links = len(results) + len(local_records)
    total_links = max(1, len(source_links))
    if progress_callback is not None and completed_links:
        progress_callback(completed_links, total_links)
    with concurrent.futures.ThreadPoolExecutor(max_workers=source_fetch_workers) as executor:
        futures = {
            executor.submit(fetch_url, url, sorted(source_refs), paths.links_dir, settings): url
            for url, source_refs in sorted(remote_links.items())
        }
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            url = record["url"]
            cache_hash = source_index_cache.input_hash(url, sorted(remote_links.get(url, set())), settings_fingerprint)
            if record.get("status") == "not-modified" and isinstance(source_cache, dict):
                cached = source_index_cache.lookup(source_cache, url, cache_hash)
                if cached is not None:
                    cached["conditional_not_modified"] = True
                    source_cache["stats"]["conditional_hits"] = int(source_cache["stats"].get("conditional_hits", 0)) + 1
                    results.append(cached)
                    completed_links += 1
                    if progress_callback is not None:
                        progress_callback(completed_links, total_links)
                    continue
            if isinstance(source_cache, dict):
                source_index_cache.store(source_cache, url, cache_hash, record)
            results.append(record)
            completed_links += 1
            if progress_callback is not None:
                progress_callback(completed_links, total_links)
    results.extend(local_records)
    return sorted(results, key=lambda item: (item["status"], item["domain"], item["url"]))


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False))


def write_note(path: Path, body: str) -> None:
    ensure_dir(path.parent)
    path.write_text(body.rstrip() + "\n")


def record_timing(timings: dict[str, Any], stage: str, started: float, **metadata: Any) -> None:
    timings.setdefault("stages", {})[stage] = {
        "seconds": round(time.perf_counter() - started, 4),
        **metadata,
    }


def write_performance_summary(paths: Paths, payload: dict[str, Any]) -> None:
    summary_path = paths.json_dir / "performance_summary.json"
    existing: dict[str, Any] = {}
    if summary_path.exists():
        try:
            parsed = json.loads(summary_path.read_text(encoding="utf-8"))
            existing = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            existing = {}
    existing.update(payload)
    write_json(summary_path, existing)


def sanitize_vault_notes(vault_path: Path) -> dict[str, int]:
    module_path = Path(__file__).with_name("sanitize_vault_privacy.py")
    spec = importlib.util.spec_from_file_location("sanitize_vault_privacy_runtime", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.sanitize_vault_markdown(vault_path)


def support_article_index(articles: list[dict[str, Any]], docx_extracts: list[dict[str, Any]], area_key: str) -> str:
    support_count = sum(1 for item in articles if item["category"] == "support-article")
    ref_count = len(articles) - support_count
    top_articles = sorted(articles, key=lambda item: item["title"].lower())[:120]
    lines = [
        "---",
        "type: hub",
        f"area: {area_key}",
        "source: generated",
        "tags:",
        "  - sources",
        "  - support-index",
        "---",
        "# Support Article Index",
        "",
        f"- Support markdown files: `{support_count}`",
        f"- Other markdown references: `{ref_count}`",
        f"- DOCX extracts: `{len(docx_extracts)}`",
        "",
        "## High-level inventory",
        "",
    ]
    for item in top_articles:
        url = item["source_url"] or "(local-only)"
        lines.append(f"- `{item['relative_path']}`: {item['title']} | {url}")
    if docx_extracts:
        lines.extend(["", "## DOCX extracts", ""])
        for item in docx_extracts:
            lines.append(f"- `{item['relative_path']}` -> `{item['extract_path']}`")
    return "\n".join(lines)


def wiki_index_note(pages: list[dict[str, Any]], area_key: str) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in pages:
        grouped[item["section"]].append(item)
    lines = [
        "---",
        "type: hub",
        f"area: {area_key}",
        "source: generated",
        "tags:",
        "  - wiki-index",
        "---",
        "# Engineering Wiki Index",
        "",
        f"- Total wiki pages indexed: `{len(pages)}`",
        "",
    ]
    for section in sorted(grouped):
        lines.append(f"## {section}")
        lines.append("")
        for item in sorted(grouped[section], key=lambda entry: entry["title"].lower()):
            lines.append(f"- `{item['relative_path']}`: {item['title']}")
        lines.append("")
    return "\n".join(lines)


def link_registry_note(links: list[dict[str, Any]], area_key: str) -> str:
    status_counts = Counter(item["status"] for item in links)
    domain_counts = Counter(item["domain"] for item in links)
    stale_doc_refs = [item for item in links if item["status"] == "stale-doc-reference"]
    lines = [
        "---",
        "type: hub",
        f"area: {area_key}",
        "source: generated",
        "tags:",
        "  - links",
        "  - traversal",
        "---",
        "# Linked Pages Registry",
        "",
        f"- Unique sanitized links: `{len(links)}`",
        "",
        "## Status counts",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: `{count}`")
    if stale_doc_refs:
        lines.extend(
            [
                "",
                "## Documentation drift",
                "",
                f"- Legacy GitLab documentation references: `{len(stale_doc_refs)}`",
                "- These links come from imported historical docs and are not treated as active source-code blockers.",
                "- Use the declared GitHub repositories in the product manifest as the code source of truth.",
            ]
        )
    lines.extend(["", "## Top domains", ""])
    for domain, count in domain_counts.most_common(30):
        lines.append(f"- {domain}: `{count}`")
    lines.extend(["", "## Mirrored samples", ""])
    for item in [entry for entry in links if entry["status"] == "mirrored"][:80]:
        lines.append(f"- {item['domain']}: {item['url']} -> `{item['mirror_path']}`")
    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[GitHub Source Of Truth]]",
            "- [[Blocked Access Registry]]",
            "- [[Restricted Source Capture Log]]",
        ]
    )
    return "\n".join(lines)


def blocked_registry_note(links: list[dict[str, Any]], area_key: str) -> str:
    blocked = [item for item in links if item["status"] in {"auth-gated", "likely-auth-gated", "needs-google-drive", "blocked"}]
    stale_doc_refs = [item for item in links if item["status"] == "stale-doc-reference"]
    lines = [
        "---",
        "type: hub",
        f"area: {area_key}",
        "source: generated",
        "tags:",
        "  - blockers",
        "  - access",
        "---",
        "# Blocked Access Registry",
        "",
        f"- Actual blocked or gated links: `{len(blocked)}`",
        f"- Legacy documentation drift links: `{len(stale_doc_refs)}`",
        "",
        "Imported GitLab links from historical docs are tracked separately from real access blockers.",
        "",
    ]
    lines.extend(["## Actual blocked or gated sources", ""])
    for item in blocked[:200]:
        refs = ", ".join(item.get("source_refs", [])[:3])
        lines.append(f"- [{item['status']}] {item['url']} | sources: `{refs}`")
    if stale_doc_refs:
        lines.extend(
            [
                "",
                "## Legacy GitLab documentation references",
                "",
                "- These are stale doc links found in imported markdown. They are not treated as current missing repositories because the active code surface for this vault is GitHub.",
                "",
            ]
        )
        for item in stale_doc_refs[:80]:
            refs = ", ".join(item.get("source_refs", [])[:3])
            lines.append(f"- [{item['status']}] {item['url']} | sources: `{refs}`")
    lines.extend(
        [
            "",
            "## Related notes",
            "",
            "- [[GitHub Source Of Truth]]",
            "- [[Linked Pages Registry]]",
            "- [[Restricted Source Capture Log]]",
        ]
    )
    return "\n".join(lines)


def repo_catalog_note(snapshots: list[dict[str, Any]], area_key: str) -> str:
    lines = [
        "---",
        "type: hub",
        f"area: {area_key}",
        "source: generated",
        "tags:",
        "  - engineering",
        "  - repo-catalog",
        "---",
        "# Repo Catalog",
        "",
        f"- Repositories indexed: `{len(snapshots)}`",
        "",
    ]
    for item in snapshots:
        lines.append(f"## {item['name']}")
        lines.append("")
        lines.append(f"- Role: `{item['role']}`")
        lines.append(f"- Branch: `{item['branch']}`")
        lines.append(f"- Local path: `{item['path']}`")
        if item["readme_title"]:
            lines.append(f"- README title: {item['readme_title']}")
        if item["readme_summary"]:
            lines.append(f"- README summary: {item['readme_summary']}")
        if item["key_files"]:
            lines.append(f"- Key files: {', '.join(f'`{name}`' for name in item['key_files'])}")
        if item["top_dirs"]:
            lines.append(f"- Top-level dirs: {', '.join(f'`{name}`' for name in item['top_dirs'][:12])}")
        if item["monorepo_apps"]:
            lines.append(f"- Monorepo apps: {', '.join(f'`{name}`' for name in item['monorepo_apps'][:15])}")
        if item["monorepo_services"]:
            lines.append(f"- Monorepo services: {', '.join(f'`{name}`' for name in item['monorepo_services'][:20])}")
        lines.append("")
    return "\n".join(lines)


def corpus_overview_note(
    articles: list[dict[str, Any]],
    docx_extracts: list[dict[str, Any]],
    links: list[dict[str, Any]],
    *,
    area_key: str,
    product_name: str,
    paths: Paths,
) -> str:
    lines = [
        "---",
        "type: review",
        f"area: {area_key}",
        "status: active",
        f"date: {DATE}",
        "source: generated",
        "review_period: source-index",
        "basb_stage: capture",
        "para_category: resource",
        "distillation_level: highlighted",
        "actionability: soon",
        "output_target: \"\"",
        "tags:",
        "  - corpus",
        "---",
        "# Corpus Overview",
        "",
        f"- Markdown files indexed: `{len(articles)}`",
        f"- DOCX files extracted: `{len(docx_extracts)}`",
        f"- Sanitized links discovered: `{len(links)}`",
        "",
        "## Working paths",
        "",
        f"- Raw corpus: `{paths.corpus}`",
        f"- Direct-fetch mirrors: `{paths.links_dir}`",
        f"- Inventory JSON: `{paths.json_dir}`",
        "",
        f"Use this note as the provenance hub for {product_name}'s raw source material and generated inventories.",
        "",
        "## Related notes",
        "",
        "- [[Support Article Index]]",
        "- [[Engineering Wiki Index]]",
        "- [[Linked Pages Registry]]",
        "- [[Blocked Access Registry]]",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source indices, mirrors, and vault notes from a product manifest.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="Bypass source extraction and linked-page caches for a clean source-index rebuild.")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    generation_config = load_generation_performance(manifest)
    rate_limit_config = load_rate_limit_config(manifest)
    rate_limiter = rate_limits.WindowRateLimiter(rate_limit_config)
    settings = product_settings(manifest, generation_config)
    settings["rate_limiter"] = rate_limiter
    paths = manifest_paths(manifest)
    ensure_dir(paths.mirror)
    ensure_dir(paths.json_dir)
    progress = generation_progress.ProgressRecorder(paths.json_dir, reset=True)
    timings: dict[str, Any] = {
        "generated_at": DATE,
        "generation_performance": generation_config,
        "rate_limits": rate_limit_config,
        "force": bool(args.force),
    }
    progress.start_run(
        "source_index",
        planned_stages=generation_progress.default_planned_stages(),
        source_extract_workers=generation_config["source_extract_workers"],
        source_fetch_workers=generation_config["source_fetch_workers"],
        force=bool(args.force),
    )
    source_extract_cache_path = paths.json_dir / "source_extract_cache.json"
    source_extract_cache = load_source_extract_cache(source_extract_cache_path)
    reset_source_extract_cache_stats(source_extract_cache)
    source_cache_path = paths.json_dir / "source_index_cache.json"
    source_cache = source_index_cache.load_cache(source_cache_path)
    source_cache["stats"] = {"hits": 0, "misses": 0, "skipped_sources": 0, "conditional_hits": 0, "invalidations": 0}
    settings["source_index_cache"] = source_cache

    progress.record("source_extract", "running")
    stage_started = time.perf_counter()
    docx_extracts = extract_docx_files(
        paths,
        source_cache=source_extract_cache,
        force=args.force,
        workers=generation_config["source_extract_workers"],
    )
    articles, support_links = collect_support_articles(paths, settings, source_cache=source_extract_cache, force=args.force)
    wiki_pages, wiki_links = collect_wiki_pages(
        paths,
        manifest,
        source_cache=source_extract_cache,
        force=args.force,
        settings=settings,
    )
    write_source_extract_cache(source_extract_cache_path, source_extract_cache)
    extracted_source_units = max(1, len(docx_extracts) + len(articles) + len(wiki_pages))
    progress.record(
        "source_extract",
        "completed",
        completed_units=extracted_source_units,
        total_units=extracted_source_units,
        docx_extracts=len(docx_extracts),
        support_articles=len(articles),
        wiki_pages=len(wiki_pages),
        cache_stats=source_extract_cache.get("stats", {}),
    )
    record_timing(
        timings,
        "source_extract",
        stage_started,
        docx_extracts=len(docx_extracts),
        markdown_sources=len(articles),
        wiki_pages=len(wiki_pages),
        cache_stats=source_extract_cache.get("stats", {}),
        worker_count=generation_config["source_extract_workers"],
    )
    all_links: dict[str, set[str]] = defaultdict(set)
    for url, refs in support_links.items():
        all_links[url].update(refs)
    for url, refs in wiki_links.items():
        all_links[url].update(refs)

    known_local_support_urls = {item["source_url"] for item in articles if item.get("source_url")}
    source_fetch_units = max(1, len(all_links))
    progress.record(
        "source_fetch",
        "running",
        completed_units=0,
        total_units=source_fetch_units,
        link_count=len(all_links),
        cache_entries=len(source_cache.get("entries", {})),
    )
    stage_started = time.perf_counter()
    link_inventory = build_link_inventory(
        all_links,
        paths,
        settings,
        known_local_support_urls=known_local_support_urls,
        force=args.force,
        progress_callback=lambda completed, total: progress.record(
            "source_fetch",
            "running",
            completed_units=completed,
            total_units=total,
            link_count=len(all_links),
            cache_entries=len(source_cache.get("entries", {})),
        ),
    )
    source_index_cache.write_cache(source_cache_path, source_cache)
    record_timing(
        timings,
        "source_fetch",
        stage_started,
        link_count=len(link_inventory),
        cache_stats=source_cache.get("stats", {}),
        worker_count=generation_config["source_fetch_workers"],
    )
    progress.record(
        "source_fetch",
        "completed",
        completed_units=source_fetch_units,
        total_units=source_fetch_units,
        link_count=len(link_inventory),
        cache_stats=source_cache.get("stats", {}),
    )
    stage_started = time.perf_counter()
    repo_snapshots = collect_repo_snapshots(manifest, paths)
    record_timing(timings, "repo_snapshots", stage_started, repos=len(repo_snapshots))

    stage_started = time.perf_counter()
    write_json(paths.json_dir / "docx_extracts.json", docx_extracts)
    write_json(paths.json_dir / "support_articles.json", articles)
    write_json(paths.json_dir / "wiki_pages.json", wiki_pages)
    write_json(paths.json_dir / "external_links.json", link_inventory)
    write_json(paths.json_dir / "repo_snapshots.json", repo_snapshots)
    rate_limits.write_rate_limit_inventory(
        paths.json_dir / "rate_limit_events.json",
        config=rate_limit_config,
        events=rate_limiter.recorder.events(),
    )
    record_timing(timings, "inventory_write", stage_started)

    stage_started = time.perf_counter()
    area_key = settings["product_slug"]
    write_note(
        paths.vault / "10 Sources" / "Corpus Overview.md",
        corpus_overview_note(
            articles,
            docx_extracts,
            link_inventory,
            area_key=area_key,
            product_name=settings["product_name"],
            paths=paths,
        ),
    )
    write_note(paths.vault / "10 Sources" / "Support Article Index.md", support_article_index(articles, docx_extracts, area_key))
    write_note(paths.vault / "10 Sources" / "Engineering Wiki Index.md", wiki_index_note(wiki_pages, area_key))
    write_note(paths.vault / "10 Sources" / "Linked Pages Registry.md", link_registry_note(link_inventory, area_key))
    write_note(paths.vault / "30 Engineering" / "Blocked Access Registry.md", blocked_registry_note(link_inventory, area_key))
    write_note(paths.vault / "30 Engineering" / "Repo Catalog.md", repo_catalog_note(repo_snapshots, area_key))
    record_timing(timings, "source_note_write", stage_started)
    stage_started = time.perf_counter()
    sanitize_summary = sanitize_vault_notes(paths.vault)
    record_timing(timings, "source_sanitize", stage_started, vault_sanitizer=sanitize_summary)
    timings["total_seconds"] = round(sum(item["seconds"] for item in timings.get("stages", {}).values()), 4)
    timings["source_extract_cache"] = source_extract_cache.get("stats", {})
    timings["source_index_cache"] = source_cache.get("stats", {})
    write_json(paths.json_dir / "source_index_timings.json", timings)
    write_performance_summary(
        paths,
        {
            "source_index": {
                "total_seconds": timings["total_seconds"],
                "force": bool(args.force),
                "source_extract_cache": source_extract_cache.get("stats", {}),
                "source_index_cache": source_cache.get("stats", {}),
                "timings_path": str(paths.json_dir / "source_index_timings.json"),
            }
        },
    )
    progress.record(
        "source_index",
        "completed",
        completed_units=5,
        total_units=5,
        vault_sanitizer=sanitize_summary,
        cache_stats=source_cache.get("stats", {}),
    )

    print(json.dumps(
        {
            "docx_extracts": len(docx_extracts),
            "markdown_sources": len(articles),
            "wiki_pages": len(wiki_pages),
            "links": len(link_inventory),
            "repos": len(repo_snapshots),
            "mirror_dir": str(paths.links_dir),
            "inventory_dir": str(paths.json_dir),
            "source_index_cache": source_cache.get("stats", {}),
            "source_extract_cache": source_extract_cache.get("stats", {}),
            "source_index_timings": str(paths.json_dir / "source_index_timings.json"),
            "vault_sanitizer": sanitize_summary,
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
