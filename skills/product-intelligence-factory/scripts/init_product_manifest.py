#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def build_manifest(args: argparse.Namespace) -> dict[str, object]:
    workspace = Path(args.workspace).expanduser().resolve()
    slug = args.slug
    return {
        "product": {
            "name": args.name,
            "slug": slug,
            "mode": args.mode,
            "vault_path": str(Path(args.vault).expanduser().resolve()),
            "workspace_path": str(workspace),
        },
        "sources": {
            "corpus_path": str((workspace / "_source_corpus" / slug).resolve()),
            "mirror_path": str((workspace / "_source_extract" / slug).resolve()),
            "docx_extract_path": str((workspace / "_source_extract" / "docx_text").resolve()),
            "auth_cache_path": str((workspace / f"_{slug}_auth_cache.json").resolve()),
            "support_login": "browser-session",
        },
        "repositories": {
            "local_clone_root": str((workspace / "_repos").resolve()),
            "safe_mirror_root": str((workspace / "_repo_mirrors").resolve()),
            "items": [
                {
                    "owner": "org",
                    "name": "repo-name",
                    "role": "core-app",
                    "default_branch": "main",
                    "local_path": str((workspace / "_repos" / "repo-name").resolve()),
                    "url": "https://github.com/org/repo-name",
                }
            ],
        },
        "automation_pack": {
            "source_truth_sync": {
                "automation_id": f"{slug}-source-truth-sync",
                "status": "planned",
            },
            "pr_merge_sync": {
                "automation_id": f"{slug}-pr-merge-sync",
                "status": "planned",
            },
            "repo_mirror_sync": {
                "automation_id": f"{slug}-repo-mirror-sync",
                "status": "planned",
            },
            "readiness_audit": {
                "automation_id": f"{slug}-engineering-readiness",
                "status": "planned",
            },
        },
        "engineering_readiness": {
            "categories": [
                {
                    "key": "reusable-import-factory",
                    "title": "Reusable product import factory",
                    "ask": 1,
                    "status": "missing",
                    "summary": "Describe the current factory status for this product.",
                    "evidence": [],
                    "missing": ["Add product-specific evidence and gaps."],
                    "next_steps": ["Turn this manifest into the first real automation-backed product run."],
                }
            ]
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a starter product intelligence manifest.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--mode", default="hybrid", choices=["product", "operations", "hybrid"])
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()

    manifest = build_manifest(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False))
    print(args.output)


if __name__ == "__main__":
    main()
