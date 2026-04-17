#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


REQUIRED_TOP_LEVEL = [
    "product",
    "sources",
    "repositories",
    "automation_pack",
    "engineering_readiness",
]


def load_manifest(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit("Manifest root must be a mapping.")
    return data


def normalize_path(value: object) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser()


def validate_manifest(data: dict[str, object], check_paths: bool) -> tuple[list[str], list[str], dict[str, object]]:
    errors: list[str] = []
    warnings: list[str] = []

    for key in REQUIRED_TOP_LEVEL:
        if key not in data:
            errors.append(f"Missing top-level key: {key}")

    product = data.get("product")
    if not isinstance(product, dict):
        errors.append("`product` must be a mapping.")
        product = {}

    for key in ["name", "slug", "mode", "vault_path", "workspace_path"]:
        if not product.get(key):
            errors.append(f"Missing product.{key}")

    sources = data.get("sources")
    if not isinstance(sources, dict):
        errors.append("`sources` must be a mapping.")
        sources = {}

    for key in ["corpus_path", "mirror_path", "auth_cache_path"]:
        if not sources.get(key):
            errors.append(f"Missing sources.{key}")

    repos = data.get("repositories")
    if not isinstance(repos, dict):
        errors.append("`repositories` must be a mapping.")
        repos = {}

    for key in ["local_clone_root", "safe_mirror_root", "items"]:
        if key not in repos:
            errors.append(f"Missing repositories.{key}")

    repo_items = repos.get("items", [])
    if not isinstance(repo_items, list) or not repo_items:
        errors.append("repositories.items must be a non-empty list.")
        repo_items = []

    for index, item in enumerate(repo_items, start=1):
        if not isinstance(item, dict):
            errors.append(f"repositories.items[{index}] must be a mapping.")
            continue
        for key in ["owner", "name", "role", "default_branch", "local_path", "url"]:
            if not item.get(key):
                errors.append(f"Missing repositories.items[{index}].{key}")

    automation_pack = data.get("automation_pack")
    if not isinstance(automation_pack, dict):
        errors.append("`automation_pack` must be a mapping.")
        automation_pack = {}

    readiness = data.get("engineering_readiness")
    if not isinstance(readiness, dict):
        errors.append("`engineering_readiness` must be a mapping.")
        readiness = {}

    categories = readiness.get("categories", [])
    if not isinstance(categories, list) or not categories:
        warnings.append("engineering_readiness.categories is empty.")
        categories = []

    if check_paths:
        path_fields = [
            ("product.vault_path", product.get("vault_path"), True),
            ("product.workspace_path", product.get("workspace_path"), True),
            ("sources.corpus_path", sources.get("corpus_path"), True),
            ("sources.mirror_path", sources.get("mirror_path"), False),
            ("sources.docx_extract_path", sources.get("docx_extract_path"), False),
            ("sources.auth_cache_path", sources.get("auth_cache_path"), False),
            ("repositories.local_clone_root", repos.get("local_clone_root"), True),
            ("repositories.safe_mirror_root", repos.get("safe_mirror_root"), False),
        ]
        for label, raw_value, should_exist in path_fields:
            path = normalize_path(raw_value)
            if path is None:
                continue
            if should_exist and not path.exists():
                warnings.append(f"Path does not exist yet: {label} -> {path}")

        for index, item in enumerate(repo_items, start=1):
            path = normalize_path(item.get("local_path"))
            if path and not path.exists():
                warnings.append(f"Repo local_path missing: repositories.items[{index}].local_path -> {path}")

    summary = {
        "product": product.get("name"),
        "slug": product.get("slug"),
        "mode": product.get("mode"),
        "repo_count": len(repo_items),
        "readiness_category_count": len(categories),
        "automation_count": len(automation_pack),
    }
    return errors, warnings, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a product intelligence manifest.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--check-paths", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data = load_manifest(args.manifest)
    errors, warnings, summary = validate_manifest(data, check_paths=args.check_paths)

    payload = {
        "manifest": str(args.manifest),
        "summary": summary,
        "errors": errors,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Manifest: {args.manifest}")
        print(f"Product: {summary['product']} ({summary['slug']})")
        print(f"Mode: {summary['mode']}")
        print(f"Repositories: {summary['repo_count']}")
        print(f"Readiness categories: {summary['readiness_category_count']}")
        print(f"Automations: {summary['automation_count']}")
        if warnings:
            print("Warnings:")
            for item in warnings:
                print(f"- {item}")
        if errors:
            print("Errors:")
            for item in errors:
                print(f"- {item}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
