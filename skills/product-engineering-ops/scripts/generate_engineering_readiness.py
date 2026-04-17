#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

import yaml


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
