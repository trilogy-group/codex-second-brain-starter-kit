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
            "support_article_url_template": "",
            "stale_doc_hosts": [],
        },
        "profile": {
            "intelligence_path": str((workspace / "config" / "intelligence-profile.yaml").resolve()),
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
                    "key": "source-coverage-and-provenance",
                    "title": "Source coverage and provenance",
                    "ask": 1,
                    "status": "missing",
                    "summary": "Describe how well raw source material, extracts, and provenance are preserved for this product.",
                    "evidence": [],
                    "missing": ["Raw source inventories and provenance notes still need to be generated."],
                    "next_steps": ["Run the source-index build and connect the resulting inventory notes to the vault."],
                },
                {
                    "key": "linked-page-capture-completeness",
                    "title": "Linked-page capture completeness",
                    "ask": 2,
                    "status": "missing",
                    "summary": "Describe the current state of direct fetches, browser-assisted capture, and unresolved restricted links.",
                    "evidence": [],
                    "missing": ["No linked-page registry or blocker registry has been created yet."],
                    "next_steps": ["Classify linked pages into mirrored, local evidence, restricted, or stale-documentation buckets."],
                },
                {
                    "key": "code-and-repo-intelligence",
                    "title": "Code and repo intelligence",
                    "ask": 3,
                    "status": "missing",
                    "summary": "Describe how well repositories are mapped into repo notes, code references, and representative code surfaces.",
                    "evidence": [],
                    "missing": ["Repository notes and code-reference notes still need to be generated."],
                    "next_steps": ["Populate repository entries, run the rebuild, and review repo and code-reference notes."],
                },
                {
                    "key": "architecture-and-runtime-understanding",
                    "title": "Architecture and runtime understanding",
                    "ask": 4,
                    "status": "missing",
                    "summary": "Describe how well the vault explains service boundaries, runtime topology, and operational surfaces.",
                    "evidence": [],
                    "missing": ["No architecture or runtime notes are connected yet."],
                    "next_steps": ["Use the generated repo and code notes to draft an architecture and service map."],
                },
                {
                    "key": "support-to-code-traceability",
                    "title": "Support-to-code traceability",
                    "ask": 5,
                    "status": "missing",
                    "summary": "Describe how support and documentation evidence map to implementation paths and services.",
                    "evidence": [],
                    "missing": ["Support, wiki, and code references are not yet linked into a traceability layer."],
                    "next_steps": ["Connect the highest-value support and wiki notes to relevant repos, files, and capability hubs."],
                },
                {
                    "key": "runbook-and-setup-coverage",
                    "title": "Runbook and setup coverage",
                    "ask": 6,
                    "status": "missing",
                    "summary": "Describe how well setup guides, runbooks, deployment notes, and operational references are covered.",
                    "evidence": [],
                    "missing": ["Operational runbooks and local setup coverage have not been synthesized yet."],
                    "next_steps": ["Promote setup and runbook sources into dedicated notes and flag restricted operational dependencies."],
                },
                {
                    "key": "blocked-dependencies-and-manual-work",
                    "title": "Blocked dependencies and manual work",
                    "ask": 7,
                    "status": "missing",
                    "summary": "Describe what still requires manual access, manual traversal, or human follow-up.",
                    "evidence": [],
                    "missing": ["No blocker registry or manual-gap log has been created yet."],
                    "next_steps": ["Capture blocked URLs, stale references, and remaining manual dependencies explicitly instead of silently skipping them."],
                },
                {
                    "key": "future-automation-opportunities",
                    "title": "Future automation opportunities",
                    "ask": 8,
                    "status": "missing",
                    "summary": "Describe what should be automated after the first manual ingestion path is trusted.",
                    "evidence": [],
                    "missing": ["Automation candidates have not yet been identified from the first real run."],
                    "next_steps": ["Identify safe refresh points for source sync, repo sync, restricted-link retry, and readiness regeneration."],
                },
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
