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
