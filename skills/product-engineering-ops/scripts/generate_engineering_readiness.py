#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

import yaml


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def load_manifest(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit("Manifest root must be a mapping.")
    return data


def exists(path_value: object) -> bool:
    if not path_value:
        return False
    return Path(str(path_value)).expanduser().exists()


def automation_file(automation_id: str | None) -> Path | None:
    if not automation_id:
        return None
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return codex_home / "automations" / automation_id / "automation.toml"


def parse_frontmatter(path: Path) -> dict[str, object]:
    match = FRONTMATTER_RE.match(path.read_text(errors="ignore"))
    if not match:
        return {}
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def vault_basb_metrics(vault_path: Path | None) -> dict[str, int | str]:
    if not vault_path or not vault_path.exists():
        return {}
    counts: Counter[str] = Counter()
    missing_basb = 0
    raw_only = 0
    output_issues = 0
    packet_issues = 0
    weekly_reviews = 0
    basb_required = {"basb_stage", "para_category", "distillation_level", "actionability"}
    durable_types = {
        "area",
        "problem",
        "initiative",
        "decision",
        "experiment",
        "metric",
        "insight",
        "capture",
        "review",
        "concept",
        "intermediate-packet",
        "output",
        "archive-record",
    }
    for path in vault_path.rglob("*.md"):
        if ".obsidian" in path.parts or "90 Templates" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        frontmatter = parse_frontmatter(path)
        note_type = str(frontmatter.get("type", "")).strip()
        if note_type:
            counts[note_type] += 1
        if note_type in durable_types and any(not frontmatter.get(field) for field in basb_required):
            missing_basb += 1
        if str(frontmatter.get("distillation_level", "")).strip() == "raw":
            if "## Essence" not in text and "## Use in current project" not in text:
                raw_only += 1
        if note_type == "output":
            evidence_section = text.split("## Evidence", 1)[1] if "## Evidence" in text else ""
            if "[[" not in evidence_section or not frontmatter.get("source_packet"):
                output_issues += 1
        if note_type == "intermediate-packet":
            if not any(target in text for target in ("[[Output Pipeline]]", "[[Initiative", "[[Decision", "[[Weekly Review", "[[Weekly Synthesis")):
                packet_issues += 1
        if note_type == "review":
            tags = frontmatter.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            if "weekly-review" in tags or path.name.startswith("Weekly Review"):
                weekly_reviews += 1
    packet_count = counts.get("intermediate-packet", 0)
    output_count = counts.get("output", 0)
    conversion_rate = f"{round((output_count / packet_count) * 100)}%" if packet_count else "0%"
    return {
        "intermediate_packets": packet_count,
        "output_candidates": output_count,
        "archive_records": counts.get("archive-record", 0),
        "weekly_reviews": weekly_reviews,
        "raw_only_notes": raw_only,
        "missing_basb_notes": missing_basb,
        "output_issues": output_issues,
        "packet_issues": packet_issues,
        "basb_issue_count": missing_basb + raw_only + output_issues + packet_issues,
        "output_conversion_rate": conversion_rate,
    }


def load_json_if_exists(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def inventory_quality_metrics(mirror_path: Path | None) -> dict[str, int | str]:
    if not mirror_path:
        return {}
    inventory_dir = mirror_path / "inventories"
    if not inventory_dir.exists():
        return {}
    code_intel = load_json_if_exists(inventory_dir / "code_intelligence.json")
    semantic = load_json_if_exists(inventory_dir / "semantic_clusters.json")
    embedding_cache = load_json_if_exists(inventory_dir / "embedding_cache.json")
    llm_cache = load_json_if_exists(inventory_dir / "llm_cluster_cache.json")
    if not code_intel and not semantic and not embedding_cache and not llm_cache:
        return {}
    summary = code_intel.get("summary") if isinstance(code_intel.get("summary"), dict) else {}
    graph = code_intel.get("graph") if isinstance(code_intel.get("graph"), dict) else {}
    semantic_stats = semantic.get("stats") if isinstance(semantic.get("stats"), dict) else {}
    clusters = semantic.get("clusters") if isinstance(semantic.get("clusters"), list) else []
    cache_items = embedding_cache.get("items") if isinstance(embedding_cache.get("items"), dict) else {}
    llm_cache_items = llm_cache.get("items") if isinstance(llm_cache.get("items"), dict) else {}
    dependency_graph = graph.get("dependencies") if isinstance(graph.get("dependencies"), list) else []
    hits = int(semantic_stats.get("cache_hits", 0) or 0)
    misses = int(semantic_stats.get("cache_misses", 0) or 0)
    total_cache_events = hits + misses
    return {
        "parsed_files": int(summary.get("parsed_files", 0) or 0),
        "parse_failures": int(summary.get("parse_failures", 0) or 0),
        "ast_parsed_files": int(summary.get("ast_parsed_files", 0) or 0),
        "ast_node_count": int(summary.get("ast_node_count", 0) or 0),
        "route_count": int(summary.get("route_count", 0) or 0),
        "schema_count": int(summary.get("schema_count", 0) or 0),
        "test_anchors": int(summary.get("test_anchor_count", 0) or 0),
        "dependency_edges": int(summary.get("dependency_edges", len(dependency_graph)) or 0),
        "semantic_clusters": len(clusters),
        "embedding_cache_items": len(cache_items),
        "embedding_cache_hit_rate": f"{round((hits / total_cache_events) * 100)}%" if total_cache_events else "0%",
        "embedding_cache_hits": hits,
        "embedding_cache_misses": misses,
        "openai_failures": int(semantic_stats.get("openai_failures", 0) or 0),
        "llm_cache_items": len(llm_cache_items),
        "llm_cache_hits": int(semantic_stats.get("llm_cache_hits", 0) or 0),
        "llm_cache_misses": int(semantic_stats.get("llm_cache_misses", 0) or 0),
        "llm_failures": int(semantic_stats.get("llm_failures", 0) or 0),
    }


def render_report(manifest: dict[str, object], manifest_path: Path) -> str:
    product = manifest.get("product") or {}
    sources = manifest.get("sources") or {}
    repositories = manifest.get("repositories") or {}
    automation_pack = manifest.get("automation_pack") or {}
    readiness = manifest.get("engineering_readiness") or {}
    categories = readiness.get("categories") or []

    counts = Counter()
    for category in categories:
        counts[str(category.get("status", "missing"))] += 1

    runtime_checks = [
        ("Vault path exists", exists(product.get("vault_path"))),
        ("Workspace path exists", exists(product.get("workspace_path"))),
        ("Source corpus exists", exists(sources.get("corpus_path"))),
        ("Source mirror exists", exists(sources.get("mirror_path"))),
        ("Auth cache exists", exists(sources.get("auth_cache_path"))),
        ("Local clone root exists", exists(repositories.get("local_clone_root"))),
        ("Safe mirror root exists", exists(repositories.get("safe_mirror_root"))),
    ]
    vault_path = Path(str(product.get("vault_path", ""))).expanduser() if product.get("vault_path") else None
    mirror_path = Path(str(sources.get("mirror_path", ""))).expanduser() if sources.get("mirror_path") else None
    basb_metrics = vault_basb_metrics(vault_path)
    inventory_metrics = inventory_quality_metrics(mirror_path)
    if vault_path:
        runtime_checks.extend(
            [
                ("CODE dashboard exists", (vault_path / "00 Home" / "CODE Dashboard.md").exists()),
                ("PARA map exists", (vault_path / "00 Home" / "PARA Map.md").exists()),
                ("Output pipeline exists", (vault_path / "00 Home" / "Output Pipeline.md").exists()),
                ("Output candidates folder exists", (vault_path / "30 Initiatives" / "Output Candidates").exists()),
                ("Intermediate packet index exists", (vault_path / "40 Research" / "Intermediate Packets" / "Intermediate Packet Index.md").exists()),
                ("Weekly review folder exists", (vault_path / "70 Journal" / "Reviews").exists()),
                ("Archive index exists", (vault_path / "90 Archive" / "Archive Index.md").exists()),
            ]
        )

    automation_checks = []
    for key, item in automation_pack.items():
        if not isinstance(item, dict):
            continue
        automation_id = item.get("automation_id")
        path = automation_file(str(automation_id) if automation_id else None)
        automation_checks.append(
            (
                key,
                str(automation_id or ""),
                bool(path and path.exists()),
                str(item.get("status", "unknown")),
            )
        )

    lines: list[str] = [
        f"# {product.get('name', 'Product')} Engineering Readiness Report",
        "",
        f"- Manifest: `{manifest_path}`",
        f"- Product slug: `{product.get('slug', '')}`",
        f"- Mode: `{product.get('mode', '')}`",
        f"- Repositories declared: `{len(repositories.get('items') or [])}`",
        "",
        "## Status Summary",
        "",
        f"- Done: `{counts.get('done', 0)}`",
        f"- Partial: `{counts.get('partial', 0)}`",
        f"- Missing: `{counts.get('missing', 0)}`",
        "",
        "## Runtime Checks",
        "",
    ]

    for label, ok in runtime_checks:
        lines.append(f"- {label}: `{'yes' if ok else 'no'}`")

    lines.extend(["", "## Automation Checks", ""])
    for key, automation_id, exists_on_disk, status in automation_checks:
        lines.append(
            f"- {key}: id `{automation_id or 'missing'}`, manifest status `{status}`, "
            f"installed `{'yes' if exists_on_disk else 'no'}`"
        )

    if basb_metrics:
        lines.extend(["", "## Product BASB Quality Metrics", ""])
        lines.append(f"- Intermediate packets: `{basb_metrics['intermediate_packets']}`")
        lines.append(f"- Output candidates: `{basb_metrics['output_candidates']}`")
        lines.append(f"- Output conversion rate: `{basb_metrics['output_conversion_rate']}`")
        lines.append(f"- Archive records: `{basb_metrics['archive_records']}`")
        lines.append(f"- Weekly reviews: `{basb_metrics['weekly_reviews']}`")
        lines.append(f"- Raw-only notes: `{basb_metrics['raw_only_notes']}`")
        lines.append(f"- Missing BASB metadata notes: `{basb_metrics['missing_basb_notes']}`")
        lines.append(f"- Output issues: `{basb_metrics['output_issues']}`")
        lines.append(f"- Packet issues: `{basb_metrics['packet_issues']}`")
        lines.append(f"- BASB issue count: `{basb_metrics['basb_issue_count']}`")

    if inventory_metrics:
        lines.extend(["", "## Code Intelligence And Semantic Metrics", ""])
        lines.append(f"- Parsed files: `{inventory_metrics['parsed_files']}`")
        lines.append(f"- Parse failures: `{inventory_metrics['parse_failures']}`")
        lines.append(f"- AST parsed files: `{inventory_metrics['ast_parsed_files']}`")
        lines.append(f"- AST nodes: `{inventory_metrics['ast_node_count']}`")
        lines.append(f"- Routes: `{inventory_metrics['route_count']}`")
        lines.append(f"- Schemas/data contracts: `{inventory_metrics['schema_count']}`")
        lines.append(f"- Test anchors: `{inventory_metrics['test_anchors']}`")
        lines.append(f"- Dependency edges: `{inventory_metrics['dependency_edges']}`")
        lines.append(f"- Semantic clusters: `{inventory_metrics['semantic_clusters']}`")
        lines.append(f"- Embedding cache items: `{inventory_metrics['embedding_cache_items']}`")
        lines.append(f"- Embedding cache hit rate: `{inventory_metrics['embedding_cache_hit_rate']}`")
        lines.append(f"- OpenAI failures: `{inventory_metrics['openai_failures']}`")
        lines.append(f"- LLM synthesis cache items: `{inventory_metrics['llm_cache_items']}`")
        lines.append(f"- LLM synthesis cache hits: `{inventory_metrics['llm_cache_hits']}`")
        lines.append(f"- LLM synthesis failures: `{inventory_metrics['llm_failures']}`")

    lines.extend(["", "## Readiness Categories", ""])
    for category in categories:
        title = category.get("title", category.get("key", "Untitled"))
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"- Ask: `{category.get('ask', '')}`")
        lines.append(f"- Status: `{category.get('status', 'missing')}`")
        summary = category.get("summary")
        if summary:
            lines.append(f"- Summary: {summary}")
        evidence = category.get("evidence") or []
        missing = category.get("missing") or []
        next_steps = category.get("next_steps") or []
        if evidence:
            lines.append("- Evidence:")
            for item in evidence:
                lines.append(f"  - `{item}`")
        if missing:
            lines.append("- Missing:")
            for item in missing:
                lines.append(f"  - {item}")
        if next_steps:
            lines.append("- Next steps:")
            for item in next_steps:
                lines.append(f"  - {item}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an engineering readiness report from a product manifest.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    report = render_report(manifest=manifest, manifest_path=args.manifest)

    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(report)
        print(args.write)
        return

    print(report)


if __name__ == "__main__":
    main()
