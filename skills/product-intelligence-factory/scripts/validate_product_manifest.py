#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import openai_responses


REQUIRED_TOP_LEVEL = [
    "product",
    "sources",
    "profile",
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


def validate_synthesis_model(errors: list[str], field: str, value: object) -> None:
    try:
        openai_responses.ensure_allowed_synthesis_model(str(value or ""), field=field)
    except ValueError as exc:
        errors.append(str(exc))


def validate_reasoning_effort(errors: list[str], field: str, value: object) -> None:
    try:
        openai_responses.normalize_reasoning_effort(value)
    except ValueError as exc:
        errors.append(f"{field} {exc}")


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

    profile = data.get("profile")
    if not isinstance(profile, dict):
        errors.append("`profile` must be a mapping.")
        profile = {}

    if not profile.get("intelligence_path"):
        errors.append("Missing profile.intelligence_path")
    else:
        profile_path = normalize_path(profile.get("intelligence_path"))
        if profile_path and profile_path.exists():
            profile_data = yaml.safe_load(profile_path.read_text()) or {}
            if isinstance(profile_data, dict):
                semantic = profile_data.get("semantic_clustering") or {}
                if semantic and semantic.get("provider", "openai") != "openai":
                    errors.append("profile semantic_clustering.provider must be `openai`.")
                if semantic and not semantic.get("embedding_model"):
                    errors.append("profile semantic_clustering.embedding_model is required when semantic clustering is configured.")
                if semantic and semantic.get("llm_cluster_synthesis", True) and not semantic.get("llm_model"):
                    errors.append("profile semantic_clustering.llm_model is required when LLM cluster synthesis is enabled.")
                if semantic and semantic.get("llm_cluster_synthesis", True):
                    if semantic.get("llm_model"):
                        validate_synthesis_model(errors, "profile semantic_clustering.llm_model", semantic.get("llm_model"))
                    if not semantic.get("reasoning_effort"):
                        errors.append("profile semantic_clustering.reasoning_effort is required when LLM cluster synthesis is enabled.")
                    else:
                        validate_reasoning_effort(
                            errors,
                            "profile semantic_clustering.reasoning_effort",
                            semantic.get("reasoning_effort"),
                        )
                code = profile_data.get("code_intelligence") or {}
                try:
                    max_files = int(code.get("max_files_per_repo", 1))
                except (TypeError, ValueError):
                    max_files = 0
                if code and max_files <= 0:
                    errors.append("profile code_intelligence.max_files_per_repo must be positive.")
                if code and code.get("parser_mode", "ast-when-available") not in {"ast-when-available", "regex-only"}:
                    errors.append("profile code_intelligence.parser_mode must be `ast-when-available` or `regex-only`.")
                if code and code.get("source_file_mode", "git-tracked") not in {"git-tracked", "all"}:
                    errors.append("profile code_intelligence.source_file_mode must be `git-tracked` or `all`.")
                business = profile_data.get("business_value") or {}
                if isinstance(business, dict) and business:
                    model = str(business.get("llm_model") or "").strip()
                    if not model:
                        errors.append("profile business_value.llm_model is required.")
                    else:
                        validate_synthesis_model(errors, "profile business_value.llm_model", model)
                    validate_reasoning_effort(
                        errors,
                        "profile business_value.reasoning_effort",
                        business.get("reasoning_effort", "high"),
                    )
                    for field in ("synthesis_workers", "batch_size", "timeout_seconds", "max_repair_attempts"):
                        if field not in business:
                            continue
                        if str(business[field]).strip().lower() == "auto":
                            errors.append(f"profile business_value.{field} must be an explicit positive integer; auto mode is disabled.")
                            continue
                        try:
                            parsed = int(business[field])
                        except (TypeError, ValueError):
                            parsed = 0
                        if parsed <= 0:
                            errors.append(f"profile business_value.{field} must be positive.")
                retrieval = profile_data.get("retrieval_index") or {}
                if isinstance(retrieval, dict):
                    if "max_candidates_per_source" in retrieval:
                        try:
                            candidates = int(retrieval["max_candidates_per_source"])
                        except (TypeError, ValueError):
                            candidates = 0
                        if candidates <= 0:
                            errors.append("profile retrieval_index.max_candidates_per_source must be positive.")
                    if "min_score" in retrieval:
                        try:
                            min_score = float(retrieval["min_score"])
                        except (TypeError, ValueError):
                            min_score = -1.0
                        if min_score < 0:
                            errors.append("profile retrieval_index.min_score must be zero or greater.")
                generation = profile_data.get("generation_performance") or {}
                worker_fields = [
                    "parallel_workers",
                    "source_extract_workers",
                    "source_fetch_workers",
                    "repo_analysis_workers",
                    "code_analysis_workers",
                    "note_render_workers",
                    "embedding_workers",
                    "llm_synthesis_workers",
                    "embedding_batch_size",
                ]
                for field in worker_fields:
                    if field not in generation:
                        continue
                    if str(generation[field]).strip().lower() == "auto":
                        errors.append(f"profile generation_performance.{field} must be an explicit positive integer; auto mode is disabled.")
                        continue
                    try:
                        value = int(generation[field])
                    except (TypeError, ValueError):
                        value = 0
                    if value <= 0:
                        errors.append(f"profile generation_performance.{field} must be positive.")
                shard_config = generation.get("agent_shards") if isinstance(generation, dict) else {}
                if isinstance(shard_config, dict):
                    for field in ["max_shards", "max_concurrent_shards", "timeout_seconds"]:
                        if field not in shard_config:
                            continue
                        if str(shard_config[field]).strip().lower() == "auto":
                            errors.append(f"profile generation_performance.agent_shards.{field} must be an explicit positive integer; auto mode is disabled.")
                            continue
                        try:
                            value = int(shard_config[field])
                        except (TypeError, ValueError):
                            value = 0
                        if value <= 0:
                            errors.append(f"profile generation_performance.agent_shards.{field} must be positive.")
                    if "worker_mode" in shard_config and shard_config.get("worker_mode") not in {"llm-synthesis", "fixture"}:
                        errors.append("profile generation_performance.agent_shards.worker_mode must be `llm-synthesis` or `fixture`.")
                    if "shard_model" in shard_config and not str(shard_config.get("shard_model") or "").strip():
                        errors.append("profile generation_performance.agent_shards.shard_model is required.")
                    if "shard_model" in shard_config:
                        validate_synthesis_model(
                            errors,
                            "profile generation_performance.agent_shards.shard_model",
                            shard_config.get("shard_model"),
                        )
                    if shard_config.get("worker_mode", "llm-synthesis") == "llm-synthesis":
                        if not shard_config.get("reasoning_effort"):
                            errors.append("profile generation_performance.agent_shards.reasoning_effort is required for llm-synthesis.")
                        else:
                            validate_reasoning_effort(
                                errors,
                                "profile generation_performance.agent_shards.reasoning_effort",
                                shard_config.get("reasoning_effort"),
                            )
                    if "max_cards_per_shard" in shard_config:
                        try:
                            max_cards = int(shard_config["max_cards_per_shard"])
                        except (TypeError, ValueError):
                            max_cards = 0
                        if max_cards <= 0:
                            errors.append("profile generation_performance.agent_shards.max_cards_per_shard must be positive.")
                rate_limits_config = profile_data.get("rate_limits") or {}
                if isinstance(rate_limits_config, dict):
                    for field in [
                        "openai_requests_per_minute",
                        "openai_tokens_per_minute",
                        "source_fetch_requests_per_host_per_minute",
                        "retry_attempts",
                        "retry_base_seconds",
                        "retry_max_seconds",
                        "fail_fast_seconds",
                    ]:
                        if field not in rate_limits_config:
                            continue
                        if str(rate_limits_config[field]).strip().lower() == "auto":
                            errors.append(f"profile rate_limits.{field} must be explicit; auto mode is disabled.")
                            continue
                        try:
                            value = float(rate_limits_config[field])
                        except (TypeError, ValueError):
                            value = 0
                        if value <= 0:
                            errors.append(f"profile rate_limits.{field} must be positive.")
                    for field in [
                        "max_openai_requests_per_budget_window",
                        "max_openai_tokens_per_budget_window",
                        "max_openai_cost_usd_per_budget_window",
                    ]:
                        if field not in rate_limits_config:
                            continue
                        try:
                            value = float(rate_limits_config[field])
                        except (TypeError, ValueError):
                            value = -1
                        if value < 0:
                            errors.append(f"profile rate_limits.{field} must be zero or positive.")

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
            ("profile.intelligence_path", profile.get("intelligence_path"), False),
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
