#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def default_capabilities() -> list[dict[str, object]]:
    return [
        {
            "key": "platform-core",
            "title": "Platform Core",
            "description": "Core end-user and admin product behavior, navigation, and primary workflows.",
            "keywords": ["platform", "core", "dashboard", "homepage", "onboarding", "settings"],
            "repos": [],
        },
        {
            "key": "identity-and-access",
            "title": "Identity And Access",
            "description": "Authentication, authorization, roles, sessions, and sign-in flows.",
            "keywords": ["login", "sign in", "authentication", "authorization", "sso", "session", "permissions"],
            "repos": [],
        },
        {
            "key": "user-and-admin-management",
            "title": "User And Admin Management",
            "description": "User lifecycle, admin workflows, invitations, profiles, and account operations.",
            "keywords": ["user", "admin", "profile", "invite", "account", "team", "member"],
            "repos": [],
        },
        {
            "key": "content-and-communications",
            "title": "Content And Communications",
            "description": "Content authoring, messaging, notifications, email flows, and communications surfaces.",
            "keywords": ["content", "message", "messaging", "notification", "email", "newsletter", "template"],
            "repos": [],
        },
        {
            "key": "groups-targeting-and-segmentation",
            "title": "Groups Targeting And Segmentation",
            "description": "Audience definitions, targeting, segmentation, filtering, and eligibility logic.",
            "keywords": ["group", "groups", "targeting", "segment", "audience", "filter", "eligibility"],
            "repos": [],
        },
        {
            "key": "reporting-and-analytics",
            "title": "Reporting And Analytics",
            "description": "Reporting, dashboards, metrics, analytics pipelines, and insight surfaces.",
            "keywords": ["reporting", "analytics", "dashboard", "metric", "metrics", "insights", "events"],
            "repos": [],
        },
        {
            "key": "api-and-developer-platform",
            "title": "API And Developer Platform",
            "description": "APIs, SDKs, events, webhooks, schemas, and developer-facing integration surfaces.",
            "keywords": ["api", "sdk", "developer", "webhook", "event", "schema", "oauth"],
            "repos": [],
        },
        {
            "key": "integrations-and-automation",
            "title": "Integrations And Automation",
            "description": "Third-party integrations, automation surfaces, synchronization, and external connectors.",
            "keywords": ["integration", "sync", "connector", "automation", "workflow", "provider", "webhook"],
            "repos": [],
        },
        {
            "key": "billing-and-commerce",
            "title": "Billing And Commerce",
            "description": "Pricing, subscriptions, payments, invoicing, credits, or commercial entitlement flows.",
            "keywords": ["billing", "subscription", "payment", "invoice", "pricing", "credit", "commerce"],
            "repos": [],
        },
        {
            "key": "mobile-and-clients",
            "title": "Mobile And Clients",
            "description": "Mobile apps, desktop clients, SDK clients, and platform-specific client behavior.",
            "keywords": ["mobile", "ios", "android", "client", "app store", "desktop", "device"],
            "repos": [],
        },
        {
            "key": "security-and-privacy",
            "title": "Security And Privacy",
            "description": "Security posture, privacy, account protection, compliance, and data-handling safeguards.",
            "keywords": ["security", "privacy", "compliance", "captcha", "waf", "account protection", "policy"],
            "repos": [],
        },
        {
            "key": "local-runtime-and-engineering",
            "title": "Local Runtime And Engineering",
            "description": "Local setup, development workflows, deployment pipelines, CI/CD, and runbook-oriented engineering surfaces.",
            "keywords": ["local setup", "docker", "compose", "deploy", "ci", "pipeline", "runbook", "environment"],
            "repos": [],
        },
    ]


def build_profile() -> dict[str, object]:
    return {
        "semantic_clustering": {
            "provider": "openai",
            "embedding_model": "text-embedding-3-small",
            "min_cluster_size": 3,
            "similarity_threshold": 0.78,
            "max_clusters": 40,
            "llm_model": "gpt-5.5",
            "reasoning_effort": "xhigh",
            "llm_cluster_synthesis": True,
            "max_llm_clusters": 40,
        },
        "code_intelligence": {
            "max_files_per_repo": 1200,
            "include_git_history": True,
            "include_tests": True,
            "include_dependency_graph": True,
            "parser_mode": "ast-when-available",
            "source_file_mode": "git-tracked",
            "include_untracked_code": False,
        },
        "business_value": {
            "enabled": True,
            "llm_model": "gpt-5.5",
            "reasoning_effort": "xhigh",
            "require_user_problem_for_output": True,
        },
        "retrieval_index": {
            "enabled": True,
            "max_candidates_per_source": 30,
            "min_score": 0.0,
        },
        "generation_performance": {
            "parallel_workers": 24,
            "source_extract_workers": 24,
            "source_fetch_workers": 40,
            "repo_analysis_workers": 6,
            "code_analysis_workers": 12,
            "note_render_workers": 32,
            "embedding_workers": 8,
            "llm_synthesis_workers": 10,
            "embedding_batch_size": 512,
            "incremental_rebuild": True,
            "changed_scope_rebuild": True,
            "agent_shards": {
                "enabled": True,
                "max_shards": 12,
                "max_concurrent_shards": 6,
                "timeout_seconds": 1800,
                "worker_mode": "llm-synthesis",
                "shard_model": "gpt-5.5",
                "reasoning_effort": "xhigh",
                "max_cards_per_shard": 80,
            },
        },
        "rate_limits": {
            "openai_requests_per_minute": 3000,
            "openai_tokens_per_minute": 3000000,
            "source_fetch_requests_per_host_per_minute": 120,
            "retry_attempts": 6,
            "retry_base_seconds": 1.0,
            "retry_max_seconds": 90.0,
            "fail_fast_seconds": 120.0,
            "openai_budget_path": "",
            "max_openai_requests_per_budget_window": 0,
            "max_openai_tokens_per_budget_window": 0,
            "max_openai_cost_usd_per_budget_window": 0.0,
        },
        "capabilities": default_capabilities(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a starter intelligence profile for a product second brain.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(build_profile(), sort_keys=False, allow_unicode=False))
    print(args.output)


if __name__ == "__main__":
    main()
