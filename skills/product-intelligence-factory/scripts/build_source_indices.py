#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml


URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
SUPPORT_ARTICLE_URL_RE = re.compile(r"/article/(\d{4,8})(?:[/?#].*)?$", re.IGNORECASE)

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
TRAILING_CHARS = ".,;:)]}`\"'"
USER_AGENT = "ProductIntelligenceFactory/1.0 (+https://github.com/trilogy-group/codex-second-brain-starter-kit)"


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


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def product_settings(manifest: dict[str, Any]) -> dict[str, Any]:
    product = manifest.get("product") or {}
    sources = manifest.get("sources") or {}
    return {
        "product_name": str(product.get("name", "Product")),
        "product_slug": str(product.get("slug", "product")),
        "support_article_url_template": str(sources.get("support_article_url_template", "")),
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
    if parsed.netloc.endswith(".internal"):
        return None
    return url


def normalize_known_support_url(url: str) -> str:
    article_match = SUPPORT_ARTICLE_URL_RE.search(url)
    if not article_match:
        return url.split("#", 1)[0]
    parsed = urlparse(url)
    article_id = article_match.group(1)
    return f"{parsed.scheme}://{parsed.netloc}/article/{article_id}"


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value[:120] or "item"


def extract_docx_files(paths: Paths) -> list[dict[str, Any]]:
    ensure_dir(paths.docx_extract)
    results: list[dict[str, Any]] = []
    for docx_path in sorted(paths.corpus.rglob("*.docx")):
        rel = docx_path.relative_to(paths.corpus)
        out_path = paths.docx_extract / rel.with_suffix(".txt")
        ensure_dir(out_path.parent)
        try:
            completed = subprocess.run(
                ["textutil", "-convert", "txt", "-stdout", str(docx_path)],
                check=True,
                capture_output=True,
            )
            text = completed.stdout.decode("utf-8", errors="ignore")
            out_path.write_text(text)
            results.append(
                {
                    "path": str(docx_path),
                    "relative_path": str(rel),
                    "extract_path": str(out_path),
                    "title": title_from_text(text, docx_path.stem),
                    "char_count": len(text),
                }
            )
        except subprocess.CalledProcessError as exc:
            results.append(
                {
                    "path": str(docx_path),
                    "relative_path": str(rel),
                    "extract_path": str(out_path),
                    "title": docx_path.stem,
                    "error": exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else "textutil failed",
                }
            )
    return results


def collect_support_articles(paths: Paths, settings: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    articles: list[dict[str, Any]] = []
    links: dict[str, set[str]] = defaultdict(set)
    for md_path in sorted(paths.corpus.rglob("*.md")):
        rel = md_path.relative_to(paths.corpus)
        text = md_path.read_text(errors="ignore")
        article_id = rel.stem.replace("-article", "")
        source_url = support_source_url(article_id, settings)
        title = title_from_text(text, md_path.stem)
        urls = sorted({url for url in (sanitize_url(item) for item in URL_RE.findall(text)) if url})
        for url in urls:
            links[url].add(str(rel))
        articles.append(
            {
                "article_id": article_id if article_id.isdigit() else "",
                "title": title,
                "relative_path": str(rel),
                "source_url": source_url,
                "link_count": len(urls),
                "category": "support-article" if rel.name.endswith("-article.md") else "reference-doc",
            }
        )
    return articles, links


def collect_wiki_pages(paths: Paths, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    wiki_root = repo_path_by_role(manifest, "engineering-wiki")
    pages: list[dict[str, Any]] = []
    links: dict[str, set[str]] = defaultdict(set)
    if wiki_root is None or not wiki_root.exists():
        return pages, links
    for md_path in sorted(wiki_root.rglob("*.md")):
        rel = md_path.relative_to(wiki_root)
        text = md_path.read_text(errors="ignore")
        urls = sorted({url for url in (sanitize_url(item) for item in URL_RE.findall(text)) if url})
        for url in urls:
            links[url].add(f"wiki/{rel}")
        pages.append(
            {
                "title": title_from_text(text, md_path.stem),
                "relative_path": str(rel),
                "section": rel.parts[0] if len(rel.parts) > 1 else "root",
                "link_count": len(urls),
            }
        )
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

    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=8) as response:
            status_code = getattr(response, "status", response.getcode())
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            raw_bytes = response.read(512_000)
        record["http_status"] = status_code
        record["final_url"] = final_url
        record["content_type"] = content_type
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

        if any(token in body_text.lower()[:2000] for token in ("sign in", "log in", "login", "single sign-on")):
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
    except HTTPError as exc:
        record["http_status"] = exc.code
        record["status"] = "auth-gated" if exc.code in {401, 403} else "blocked"
        record["error"] = str(exc)
        return record
    except URLError as exc:
        record["status"] = "blocked"
        record["error"] = str(exc.reason)
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
) -> list[dict[str, Any]]:
    ensure_dir(paths.links_dir)
    results: list[dict[str, Any]] = []
    local_urls = {normalize_known_support_url(url) for url in (known_local_support_urls or set())}
    local_records: list[dict[str, Any]] = []
    remote_links: dict[str, set[str]] = {}
    for url, refs in sorted(source_links.items()):
        if normalize_known_support_url(url) in local_urls:
            local_records.append(
                {
                    "url": url,
                    "domain": (urlparse(url).hostname or urlparse(url).netloc).lower(),
                    "source_refs": sorted(refs),
                    "status": "local-support-evidence",
                }
            )
        else:
            remote_links[url] = refs
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_url, url, sorted(source_refs), paths.links_dir, settings): url
            for url, source_refs in sorted(remote_links.items())
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    results.extend(local_records)
    return sorted(results, key=lambda item: (item["status"], item["domain"], item["url"]))


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False))


def write_note(path: Path, body: str) -> None:
    ensure_dir(path.parent)
    path.write_text(body.rstrip() + "\n")


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
        "source: generated",
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
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    settings = product_settings(manifest)
    paths = manifest_paths(manifest)
    ensure_dir(paths.mirror)
    ensure_dir(paths.json_dir)

    docx_extracts = extract_docx_files(paths)
    articles, support_links = collect_support_articles(paths, settings)
    wiki_pages, wiki_links = collect_wiki_pages(paths, manifest)
    all_links: dict[str, set[str]] = defaultdict(set)
    for url, refs in support_links.items():
        all_links[url].update(refs)
    for url, refs in wiki_links.items():
        all_links[url].update(refs)

    known_local_support_urls = {item["source_url"] for item in articles if item.get("source_url")}
    link_inventory = build_link_inventory(
        all_links,
        paths,
        settings,
        known_local_support_urls=known_local_support_urls,
    )
    repo_snapshots = collect_repo_snapshots(manifest, paths)

    write_json(paths.json_dir / "docx_extracts.json", docx_extracts)
    write_json(paths.json_dir / "support_articles.json", articles)
    write_json(paths.json_dir / "wiki_pages.json", wiki_pages)
    write_json(paths.json_dir / "external_links.json", link_inventory)
    write_json(paths.json_dir / "repo_snapshots.json", repo_snapshots)

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
    sanitize_summary = sanitize_vault_notes(paths.vault)

    print(json.dumps(
        {
            "docx_extracts": len(docx_extracts),
            "markdown_sources": len(articles),
            "wiki_pages": len(wiki_pages),
            "links": len(link_inventory),
            "repos": len(repo_snapshots),
            "mirror_dir": str(paths.links_dir),
            "inventory_dir": str(paths.json_dir),
            "vault_sanitizer": sanitize_summary,
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
