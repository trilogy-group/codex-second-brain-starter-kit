#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Any


DEFAULT_GENERATION_PERFORMANCE: dict[str, Any] = {
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
        "reasoning_effort": "high",
        "max_cards_per_shard": 80,
    },
}

DEFAULT_RATE_LIMITS: dict[str, Any] = {
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
}

ENV_OVERRIDES = {
    "parallel_workers": ("PRODUCT_BASB_PARALLEL_WORKERS", "TYLER_SECOND_BRAIN_PARALLEL_WORKERS"),
    "source_extract_workers": ("PRODUCT_BASB_SOURCE_EXTRACT_WORKERS", "TYLER_SECOND_BRAIN_SOURCE_EXTRACT_WORKERS"),
    "source_fetch_workers": ("PRODUCT_BASB_SOURCE_FETCH_WORKERS", "TYLER_SECOND_BRAIN_SOURCE_FETCH_WORKERS"),
    "repo_analysis_workers": ("PRODUCT_BASB_REPO_ANALYSIS_WORKERS",),
    "code_analysis_workers": ("PRODUCT_BASB_CODE_ANALYSIS_WORKERS", "TYLER_SECOND_BRAIN_CODE_WORKERS"),
    "note_render_workers": ("PRODUCT_BASB_NOTE_RENDER_WORKERS", "TYLER_SECOND_BRAIN_NOTE_WORKERS"),
    "embedding_workers": ("PRODUCT_BASB_EMBEDDING_WORKERS",),
    "llm_synthesis_workers": ("PRODUCT_BASB_LLM_SYNTHESIS_WORKERS", "TYLER_SECOND_BRAIN_LLM_WORKERS"),
    "embedding_batch_size": ("PRODUCT_BASB_EMBEDDING_BATCH_SIZE",),
    "changed_scope_rebuild": ("PRODUCT_BASB_CHANGED_SCOPE_REBUILD", "TYLER_SECOND_BRAIN_CHANGED_SCOPE_REBUILD"),
    "agent_shards.enabled": ("PRODUCT_BASB_AGENT_SHARDS_ENABLED", "TYLER_SECOND_BRAIN_AGENT_SHARDS_ENABLED"),
    "agent_shards.max_shards": ("PRODUCT_BASB_AGENT_MAX_SHARDS", "TYLER_SECOND_BRAIN_AGENT_MAX_SHARDS"),
    "agent_shards.max_concurrent_shards": (
        "PRODUCT_BASB_AGENT_CONCURRENT_SHARDS",
        "TYLER_SECOND_BRAIN_AGENT_CONCURRENT_SHARDS",
    ),
    "agent_shards.timeout_seconds": (
        "PRODUCT_BASB_AGENT_SHARD_TIMEOUT_SECONDS",
        "TYLER_SECOND_BRAIN_AGENT_SHARD_TIMEOUT_SECONDS",
    ),
    "agent_shards.worker_mode": ("PRODUCT_BASB_AGENT_SHARD_WORKER_MODE",),
    "agent_shards.shard_model": ("PRODUCT_BASB_AGENT_SHARD_MODEL", "TYLER_SECOND_BRAIN_AGENT_SHARD_MODEL"),
    "agent_shards.reasoning_effort": (
        "PRODUCT_BASB_AGENT_SHARD_REASONING_EFFORT",
        "TYLER_SECOND_BRAIN_AGENT_SHARD_REASONING_EFFORT",
    ),
    "agent_shards.max_cards_per_shard": ("PRODUCT_BASB_AGENT_MAX_CARDS_PER_SHARD",),
}

RATE_LIMIT_ENV_OVERRIDES = {
    "openai_requests_per_minute": ("PRODUCT_BASB_OPENAI_REQUESTS_PER_MINUTE", "TYLER_SECOND_BRAIN_OPENAI_RPM"),
    "openai_tokens_per_minute": ("PRODUCT_BASB_OPENAI_TOKENS_PER_MINUTE", "TYLER_SECOND_BRAIN_OPENAI_TPM"),
    "source_fetch_requests_per_host_per_minute": (
        "PRODUCT_BASB_SOURCE_FETCH_REQUESTS_PER_HOST_PER_MINUTE",
        "TYLER_SECOND_BRAIN_SOURCE_FETCH_RPHM",
    ),
    "retry_attempts": ("PRODUCT_BASB_RATE_LIMIT_RETRY_ATTEMPTS", "TYLER_SECOND_BRAIN_RATE_LIMIT_RETRY_ATTEMPTS"),
    "retry_base_seconds": ("PRODUCT_BASB_RATE_LIMIT_RETRY_BASE_SECONDS",),
    "retry_max_seconds": ("PRODUCT_BASB_RATE_LIMIT_RETRY_MAX_SECONDS",),
    "fail_fast_seconds": ("PRODUCT_BASB_RATE_LIMIT_FAIL_FAST_SECONDS",),
    "openai_budget_path": ("PRODUCT_BASB_OPENAI_BUDGET_PATH", "TYLER_SECOND_BRAIN_OPENAI_BUDGET_PATH"),
    "max_openai_requests_per_budget_window": (
        "PRODUCT_BASB_MAX_OPENAI_REQUESTS_PER_BUDGET_WINDOW",
        "TYLER_SECOND_BRAIN_MAX_OPENAI_REQUESTS_PER_BUDGET_WINDOW",
    ),
    "max_openai_tokens_per_budget_window": (
        "PRODUCT_BASB_MAX_OPENAI_TOKENS_PER_BUDGET_WINDOW",
        "TYLER_SECOND_BRAIN_MAX_OPENAI_TOKENS_PER_BUDGET_WINDOW",
    ),
    "max_openai_cost_usd_per_budget_window": (
        "PRODUCT_BASB_MAX_OPENAI_COST_USD_PER_BUDGET_WINDOW",
        "TYLER_SECOND_BRAIN_MAX_OPENAI_COST_USD_PER_BUDGET_WINDOW",
    ),
}


def _explicit_positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, str) and value.strip().lower() == "auto":
        raise SystemExit(f"generation_performance.{field} must be an explicit positive integer; auto mode is disabled.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"generation_performance.{field} must be an explicit positive integer.") from exc
    if parsed <= 0:
        raise SystemExit(f"generation_performance.{field} must be greater than zero.")
    return parsed


def _explicit_positive_float(value: Any, *, field: str) -> float:
    if isinstance(value, str) and value.strip().lower() == "auto":
        raise SystemExit(f"rate_limits.{field} must be an explicit positive number; auto mode is disabled.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"rate_limits.{field} must be an explicit positive number.") from exc
    if parsed <= 0:
        raise SystemExit(f"rate_limits.{field} must be greater than zero.")
    return parsed


def _configured_value(configured: dict[str, Any], field: str, default: Any, *, config_key: str | None = None) -> Any:
    for env_name in ENV_OVERRIDES.get(field, ()):
        value = os.environ.get(env_name)
        if value not in (None, ""):
            return value
    return configured.get(config_key or field, default)


def _rate_limit_value(configured: dict[str, Any], field: str, default: Any) -> Any:
    for env_name in RATE_LIMIT_ENV_OVERRIDES.get(field, ()):
        value = os.environ.get(env_name)
        if value not in (None, ""):
            return value
    return configured.get(field, default)


def _configured_bool(configured: dict[str, Any], field: str, default: bool, *, config_key: str | None = None) -> bool:
    value = _configured_value(configured, field, default, config_key=config_key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def default_generation_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("generation_performance") or {})
    shard_config = dict(DEFAULT_GENERATION_PERFORMANCE["agent_shards"])
    shard_config.update(configured.get("agent_shards") or {})
    parallel_workers = _explicit_positive_int(
        _configured_value(configured, "parallel_workers", DEFAULT_GENERATION_PERFORMANCE["parallel_workers"]),
        field="parallel_workers",
    )
    return {
        "parallel_workers": parallel_workers,
        "source_extract_workers": _explicit_positive_int(
            _configured_value(configured, "source_extract_workers", parallel_workers),
            field="source_extract_workers",
        ),
        "source_fetch_workers": _explicit_positive_int(
            _configured_value(configured, "source_fetch_workers", DEFAULT_GENERATION_PERFORMANCE["source_fetch_workers"]),
            field="source_fetch_workers",
        ),
        "repo_analysis_workers": _explicit_positive_int(
            _configured_value(configured, "repo_analysis_workers", DEFAULT_GENERATION_PERFORMANCE["repo_analysis_workers"]),
            field="repo_analysis_workers",
        ),
        "code_analysis_workers": _explicit_positive_int(
            _configured_value(configured, "code_analysis_workers", DEFAULT_GENERATION_PERFORMANCE["code_analysis_workers"]),
            field="code_analysis_workers",
        ),
        "note_render_workers": _explicit_positive_int(
            _configured_value(configured, "note_render_workers", DEFAULT_GENERATION_PERFORMANCE["note_render_workers"]),
            field="note_render_workers",
        ),
        "embedding_workers": _explicit_positive_int(
            _configured_value(configured, "embedding_workers", DEFAULT_GENERATION_PERFORMANCE["embedding_workers"]),
            field="embedding_workers",
        ),
        "llm_synthesis_workers": _explicit_positive_int(
            _configured_value(configured, "llm_synthesis_workers", DEFAULT_GENERATION_PERFORMANCE["llm_synthesis_workers"]),
            field="llm_synthesis_workers",
        ),
        "embedding_batch_size": _explicit_positive_int(
            _configured_value(configured, "embedding_batch_size", DEFAULT_GENERATION_PERFORMANCE["embedding_batch_size"]),
            field="embedding_batch_size",
        ),
        "incremental_rebuild": bool(configured.get("incremental_rebuild", DEFAULT_GENERATION_PERFORMANCE["incremental_rebuild"])),
        "changed_scope_rebuild": _configured_bool(
            configured,
            "changed_scope_rebuild",
            DEFAULT_GENERATION_PERFORMANCE["changed_scope_rebuild"],
        ),
        "agent_shards": {
            "enabled": _configured_bool(shard_config, "agent_shards.enabled", True, config_key="enabled"),
            "max_shards": _explicit_positive_int(
                _configured_value(shard_config, "agent_shards.max_shards", 12, config_key="max_shards"),
                field="agent_shards.max_shards",
            ),
            "max_concurrent_shards": _explicit_positive_int(
                _configured_value(shard_config, "agent_shards.max_concurrent_shards", 6, config_key="max_concurrent_shards"),
                field="agent_shards.max_concurrent_shards",
            ),
            "timeout_seconds": _explicit_positive_int(
                _configured_value(shard_config, "agent_shards.timeout_seconds", 1800, config_key="timeout_seconds"),
                field="agent_shards.timeout_seconds",
            ),
            "worker_mode": str(
                _configured_value(shard_config, "agent_shards.worker_mode", "llm-synthesis", config_key="worker_mode")
            ),
            "shard_model": str(
                _configured_value(shard_config, "agent_shards.shard_model", "gpt-5.5", config_key="shard_model")
            ),
            "reasoning_effort": str(
                _configured_value(
                    shard_config,
                    "agent_shards.reasoning_effort",
                    "high",
                    config_key="reasoning_effort",
                )
            ),
            "max_cards_per_shard": _explicit_positive_int(
                _configured_value(shard_config, "agent_shards.max_cards_per_shard", 80, config_key="max_cards_per_shard"),
                field="agent_shards.max_cards_per_shard",
            ),
        },
    }


def default_rate_limit_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("rate_limits") or {})
    return {
        "openai_requests_per_minute": _explicit_positive_int(
            _rate_limit_value(configured, "openai_requests_per_minute", DEFAULT_RATE_LIMITS["openai_requests_per_minute"]),
            field="openai_requests_per_minute",
        ),
        "openai_tokens_per_minute": _explicit_positive_int(
            _rate_limit_value(configured, "openai_tokens_per_minute", DEFAULT_RATE_LIMITS["openai_tokens_per_minute"]),
            field="openai_tokens_per_minute",
        ),
        "source_fetch_requests_per_host_per_minute": _explicit_positive_int(
            _rate_limit_value(
                configured,
                "source_fetch_requests_per_host_per_minute",
                DEFAULT_RATE_LIMITS["source_fetch_requests_per_host_per_minute"],
            ),
            field="source_fetch_requests_per_host_per_minute",
        ),
        "retry_attempts": _explicit_positive_int(
            _rate_limit_value(configured, "retry_attempts", DEFAULT_RATE_LIMITS["retry_attempts"]),
            field="retry_attempts",
        ),
        "retry_base_seconds": _explicit_positive_float(
            _rate_limit_value(configured, "retry_base_seconds", DEFAULT_RATE_LIMITS["retry_base_seconds"]),
            field="retry_base_seconds",
        ),
        "retry_max_seconds": _explicit_positive_float(
            _rate_limit_value(configured, "retry_max_seconds", DEFAULT_RATE_LIMITS["retry_max_seconds"]),
            field="retry_max_seconds",
        ),
        "fail_fast_seconds": _explicit_positive_float(
            _rate_limit_value(configured, "fail_fast_seconds", DEFAULT_RATE_LIMITS["fail_fast_seconds"]),
            field="fail_fast_seconds",
        ),
        "openai_budget_path": str(_rate_limit_value(configured, "openai_budget_path", DEFAULT_RATE_LIMITS["openai_budget_path"])),
        "max_openai_requests_per_budget_window": int(
            _rate_limit_value(
                configured,
                "max_openai_requests_per_budget_window",
                DEFAULT_RATE_LIMITS["max_openai_requests_per_budget_window"],
            )
            or 0
        ),
        "max_openai_tokens_per_budget_window": int(
            _rate_limit_value(
                configured,
                "max_openai_tokens_per_budget_window",
                DEFAULT_RATE_LIMITS["max_openai_tokens_per_budget_window"],
            )
            or 0
        ),
        "max_openai_cost_usd_per_budget_window": float(
            _rate_limit_value(
                configured,
                "max_openai_cost_usd_per_budget_window",
                DEFAULT_RATE_LIMITS["max_openai_cost_usd_per_budget_window"],
            )
            or 0.0
        ),
    }
