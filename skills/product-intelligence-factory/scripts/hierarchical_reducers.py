#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evidence_cards
import incremental_cache
import openai_responses
import openai_requests
import rate_limits


DEFAULT_EVIDENCE_SCALING: dict[str, Any] = {
    "generated_notes_feed_synthesis": False,
    "max_cards_per_source_shard": 80,
    "max_cards_per_theme_shard": 80,
    "max_theme_summaries_per_capability_shard": 40,
    "max_capability_summaries_for_ontology": 60,
    "max_summary_chars": 1800,
    "unlimited_total_shards": True,
    "evidence_compaction": {
        "enabled": True,
        "max_raw_cards_per_source_group": 160,
        "max_compacted_cards_per_group": 24,
        "max_reducer_gpt_calls_per_layer_soft": 80,
        "preserve_raw_inventory": True,
    },
    "hierarchical_reducers": {
        "batch_size": 8,
        "split_on_timeout": True,
        "live_events_enabled": True,
        "source_reasoning_effort": "medium",
        "theme_reasoning_effort": "medium",
        "capability_reasoning_effort": "high",
        "ontology_reasoning_effort": "high",
    },
    "generated_note_policy": {
        "max_repo_document_notes": 600,
        "max_uploaded_document_notes": 600,
    },
}

EVIDENCE_SCALING_ENV_OVERRIDES = {
    "generated_notes_feed_synthesis": ("PRODUCT_BASB_GENERATED_NOTES_FEED_SYNTHESIS",),
    "max_cards_per_source_shard": ("PRODUCT_BASB_MAX_CARDS_PER_SOURCE_SHARD",),
    "max_cards_per_theme_shard": ("PRODUCT_BASB_MAX_CARDS_PER_THEME_SHARD",),
    "max_theme_summaries_per_capability_shard": ("PRODUCT_BASB_MAX_THEME_SUMMARIES_PER_CAPABILITY_SHARD",),
    "max_capability_summaries_for_ontology": ("PRODUCT_BASB_MAX_CAPABILITY_SUMMARIES_FOR_ONTOLOGY",),
    "max_summary_chars": ("PRODUCT_BASB_MAX_SUMMARY_CHARS",),
    "unlimited_total_shards": ("PRODUCT_BASB_UNLIMITED_TOTAL_SHARDS",),
    "evidence_compaction.enabled": ("PRODUCT_BASB_EVIDENCE_COMPACTION_ENABLED",),
    "evidence_compaction.max_raw_cards_per_source_group": ("PRODUCT_BASB_MAX_RAW_CARDS_PER_SOURCE_GROUP",),
    "evidence_compaction.max_compacted_cards_per_group": ("PRODUCT_BASB_MAX_COMPACTED_CARDS_PER_GROUP",),
    "evidence_compaction.max_reducer_gpt_calls_per_layer_soft": ("PRODUCT_BASB_MAX_REDUCER_GPT_CALLS_PER_LAYER_SOFT",),
    "evidence_compaction.preserve_raw_inventory": ("PRODUCT_BASB_PRESERVE_RAW_EVIDENCE_INVENTORY",),
    "hierarchical_reducers.batch_size": ("PRODUCT_BASB_HIERARCHICAL_REDUCER_BATCH_SIZE",),
    "hierarchical_reducers.split_on_timeout": ("PRODUCT_BASB_HIERARCHICAL_REDUCER_SPLIT_ON_TIMEOUT",),
    "hierarchical_reducers.live_events_enabled": ("PRODUCT_BASB_HIERARCHICAL_REDUCER_LIVE_EVENTS_ENABLED",),
    "hierarchical_reducers.source_reasoning_effort": (
        "PRODUCT_BASB_SOURCE_REDUCER_REASONING_EFFORT",
        "TYLER_SECOND_BRAIN_SOURCE_REDUCER_REASONING_EFFORT",
    ),
    "hierarchical_reducers.theme_reasoning_effort": (
        "PRODUCT_BASB_THEME_REDUCER_REASONING_EFFORT",
        "TYLER_SECOND_BRAIN_THEME_REDUCER_REASONING_EFFORT",
    ),
    "hierarchical_reducers.capability_reasoning_effort": (
        "PRODUCT_BASB_CAPABILITY_REDUCER_REASONING_EFFORT",
        "TYLER_SECOND_BRAIN_CAPABILITY_REDUCER_REASONING_EFFORT",
    ),
    "hierarchical_reducers.ontology_reasoning_effort": (
        "PRODUCT_BASB_ONTOLOGY_REDUCER_REASONING_EFFORT",
        "TYLER_SECOND_BRAIN_ONTOLOGY_REDUCER_REASONING_EFFORT",
    ),
    "generated_note_policy.max_repo_document_notes": ("PRODUCT_BASB_MAX_REPO_DOCUMENT_NOTES",),
    "generated_note_policy.max_uploaded_document_notes": ("PRODUCT_BASB_MAX_UPLOADED_DOCUMENT_NOTES",),
}

REDUCER_CACHE_NAMESPACE = "hierarchical_reducers"
REDUCER_PROMPT_VERSION = "product-basb-hierarchical-reducer-v2"
REDUCER_SCHEMA_VERSION = 2


def _positive_int(configured: dict[str, Any], key: str, default: int) -> int:
    for env_name in EVIDENCE_SCALING_ENV_OVERRIDES.get(key, ()):
        env_value = os.environ.get(env_name)
        if env_value not in (None, ""):
            configured = {**configured, key: env_value}
            break
    try:
        parsed = int(configured.get(key, default))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"evidence_scaling.{key} must be a positive integer.") from exc
    if parsed <= 0:
        raise SystemExit(f"evidence_scaling.{key} must be a positive integer.")
    return parsed


def _config_bool(configured: dict[str, Any], key: str, default: bool) -> bool:
    field = key.rsplit(".", 1)[-1]
    value: Any = configured.get(key, configured.get(field, default))
    for env_name in EVIDENCE_SCALING_ENV_OVERRIDES.get(key, ()):
        env_value = os.environ.get(env_name)
        if env_value not in (None, ""):
            value = env_value
            break
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _nested_positive_int(configured: dict[str, Any], key: str, default: int) -> int:
    field = key.rsplit(".", 1)[-1]
    aliased = {key: configured.get(key, configured.get(field, default))}
    return _positive_int(aliased, key, default)


def _nested_reasoning_effort(configured: dict[str, Any], key: str, default: str) -> str:
    field = key.rsplit(".", 1)[-1]
    value: Any = configured.get(key, configured.get(field, default))
    for env_name in EVIDENCE_SCALING_ENV_OVERRIDES.get(key, ()):
        env_value = os.environ.get(env_name)
        if env_value not in (None, ""):
            value = env_value
            break
    return openai_responses.normalize_reasoning_effort(value)


def default_evidence_scaling_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("evidence_scaling") or {})
    compaction_config = {
        **dict(DEFAULT_EVIDENCE_SCALING["evidence_compaction"]),
        **dict((profile or {}).get("evidence_compaction") or {}),
        **dict(configured.get("evidence_compaction") or {}),
    }
    reducer_config = {
        **dict(DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]),
        **dict((profile or {}).get("hierarchical_reducers") or {}),
        **dict(configured.get("hierarchical_reducers") or {}),
    }
    note_policy_config = {
        **dict(DEFAULT_EVIDENCE_SCALING["generated_note_policy"]),
        **dict((profile or {}).get("generated_note_policy") or {}),
        **dict(configured.get("generated_note_policy") or {}),
    }
    generated_notes_value: Any = configured.get(
        "generated_notes_feed_synthesis",
        DEFAULT_EVIDENCE_SCALING["generated_notes_feed_synthesis"],
    )
    for env_name in EVIDENCE_SCALING_ENV_OVERRIDES["generated_notes_feed_synthesis"]:
        env_value = os.environ.get(env_name)
        if env_value not in (None, ""):
            generated_notes_value = env_value
            break
    unlimited_value: Any = configured.get("unlimited_total_shards", True)
    for env_name in EVIDENCE_SCALING_ENV_OVERRIDES["unlimited_total_shards"]:
        env_value = os.environ.get(env_name)
        if env_value not in (None, ""):
            unlimited_value = env_value
            break
    return {
        "generated_notes_feed_synthesis": str(generated_notes_value).strip().lower() in {"1", "true", "yes", "on"},
        "max_cards_per_source_shard": _positive_int(
            configured,
            "max_cards_per_source_shard",
            DEFAULT_EVIDENCE_SCALING["max_cards_per_source_shard"],
        ),
        "max_cards_per_theme_shard": _positive_int(
            configured,
            "max_cards_per_theme_shard",
            DEFAULT_EVIDENCE_SCALING["max_cards_per_theme_shard"],
        ),
        "max_theme_summaries_per_capability_shard": _positive_int(
            configured,
            "max_theme_summaries_per_capability_shard",
            DEFAULT_EVIDENCE_SCALING["max_theme_summaries_per_capability_shard"],
        ),
        "max_capability_summaries_for_ontology": _positive_int(
            configured,
            "max_capability_summaries_for_ontology",
            DEFAULT_EVIDENCE_SCALING["max_capability_summaries_for_ontology"],
        ),
        "max_summary_chars": _positive_int(configured, "max_summary_chars", DEFAULT_EVIDENCE_SCALING["max_summary_chars"]),
        "unlimited_total_shards": str(unlimited_value).strip().lower() in {"1", "true", "yes", "on"},
        "evidence_compaction": {
            "enabled": _config_bool(compaction_config, "evidence_compaction.enabled", True),
            "max_raw_cards_per_source_group": _nested_positive_int(
                compaction_config,
                "evidence_compaction.max_raw_cards_per_source_group",
                int(DEFAULT_EVIDENCE_SCALING["evidence_compaction"]["max_raw_cards_per_source_group"]),
            ),
            "max_compacted_cards_per_group": _nested_positive_int(
                compaction_config,
                "evidence_compaction.max_compacted_cards_per_group",
                int(DEFAULT_EVIDENCE_SCALING["evidence_compaction"]["max_compacted_cards_per_group"]),
            ),
            "max_reducer_gpt_calls_per_layer_soft": _nested_positive_int(
                compaction_config,
                "evidence_compaction.max_reducer_gpt_calls_per_layer_soft",
                int(DEFAULT_EVIDENCE_SCALING["evidence_compaction"]["max_reducer_gpt_calls_per_layer_soft"]),
            ),
            "preserve_raw_inventory": _config_bool(compaction_config, "evidence_compaction.preserve_raw_inventory", True),
        },
        "hierarchical_reducers": {
            "batch_size": _nested_positive_int(
                reducer_config,
                "hierarchical_reducers.batch_size",
                int(DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["batch_size"]),
            ),
            "split_on_timeout": _config_bool(reducer_config, "hierarchical_reducers.split_on_timeout", True),
            "live_events_enabled": _config_bool(reducer_config, "hierarchical_reducers.live_events_enabled", True),
            "source_reasoning_effort": _nested_reasoning_effort(
                reducer_config,
                "hierarchical_reducers.source_reasoning_effort",
                str(DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["source_reasoning_effort"]),
            ),
            "theme_reasoning_effort": _nested_reasoning_effort(
                reducer_config,
                "hierarchical_reducers.theme_reasoning_effort",
                str(DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["theme_reasoning_effort"]),
            ),
            "capability_reasoning_effort": _nested_reasoning_effort(
                reducer_config,
                "hierarchical_reducers.capability_reasoning_effort",
                str(DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["capability_reasoning_effort"]),
            ),
            "ontology_reasoning_effort": _nested_reasoning_effort(
                reducer_config,
                "hierarchical_reducers.ontology_reasoning_effort",
                str(DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["ontology_reasoning_effort"]),
            ),
        },
        "generated_note_policy": {
            "max_repo_document_notes": _nested_positive_int(
                note_policy_config,
                "generated_note_policy.max_repo_document_notes",
                int(DEFAULT_EVIDENCE_SCALING["generated_note_policy"]["max_repo_document_notes"]),
            ),
            "max_uploaded_document_notes": _nested_positive_int(
                note_policy_config,
                "generated_note_policy.max_uploaded_document_notes",
                int(DEFAULT_EVIDENCE_SCALING["generated_note_policy"]["max_uploaded_document_notes"]),
            ),
        },
    }


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()
    return cleaned[:100] or "evidence"


def _source_group(card: dict[str, Any]) -> str:
    source_kind = str(card.get("source_kind") or "generated-note")
    uri = str(card.get("source_uri") or card.get("path") or card.get("id") or "")
    if source_kind == "crawled-url":
        host = urlparse(uri).netloc
        return host or "url"
    if source_kind in {"repo-code", "repo-doc"} and "/" in uri:
        return uri.split("/", 1)[0]
    if source_kind in {"uploaded-doc", "docx", "pdf"} and uri:
        return Path(uri).suffix.lstrip(".") or source_kind
    return source_kind


def _bounded_cards(cards: list[dict[str, Any]], *, max_summary_chars: int, include_generated_notes: bool) -> list[dict[str, Any]]:
    stable = evidence_cards.stable_cards(cards, include_generated_notes=include_generated_notes)
    bounded: list[dict[str, Any]] = []
    for card in stable:
        bounded.append(
            {
                **card,
                "summary": evidence_cards.compact_text(card.get("summary") or "", max_summary_chars),
            }
        )
    return bounded


def _path_family(card: dict[str, Any]) -> str:
    source_kind = str(card.get("source_kind") or "generated-note")
    uri = str(card.get("source_uri") or card.get("path") or card.get("id") or "")
    if source_kind == "crawled-url":
        parsed = urlparse(uri)
        parts = [part for part in parsed.path.split("/") if part]
        return "/".join(parts[:2]) or parsed.netloc or "url"
    parts = [part for part in uri.split("/") if part]
    if source_kind in {"repo-code", "repo-doc"} and len(parts) > 1:
        return "/".join(parts[1:4]) or parts[-1]
    if parts:
        return "/".join(parts[:3])
    return _source_group(card)


def _card_fingerprint(card: dict[str, Any]) -> str:
    return evidence_cards.stable_hash(
        {
            "source_kind": card.get("source_kind"),
            "title": card.get("title"),
            "summary": card.get("summary"),
            "source_uri": card.get("source_uri"),
        }
    )


def _salience_score(card: dict[str, Any]) -> int:
    title = str(card.get("title") or "")
    summary = str(card.get("summary") or "")
    terms = card.get("terms") if isinstance(card.get("terms"), list) else []
    score = min(30, len(summary) // 80) + min(20, len(terms) * 2)
    if card.get("code_anchors"):
        score += 30
    if str(card.get("confidence") or "").casefold() == "high":
        score += 10
    if re.search(r"\b(readme|overview|guide|workflow|architecture|product|customer|user|support|runbook)\b", title, re.I):
        score += 12
    return score


def _dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for card in cards:
        fingerprint = _card_fingerprint(card)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(card)
    return deduped


def _compact_card_family(
    *,
    source_kind: str,
    group: str,
    family: str,
    cards: list[dict[str, Any]],
    max_summary_chars: int,
) -> dict[str, Any]:
    selected = sorted(cards, key=lambda item: (-_salience_score(item), str(item.get("id") or "")))[:6]
    terms = sorted({term for card in selected for term in card.get("terms", []) if str(term).strip()})[:24]
    code_anchors = sorted({anchor for card in selected for anchor in card.get("code_anchors", []) if str(anchor).strip()})[:24]
    evidence_ids = [str(card.get("id")) for card in selected if card.get("id")]
    summary_parts = [str(card.get("summary") or card.get("title") or "") for card in selected if str(card.get("summary") or card.get("title") or "").strip()]
    summary = evidence_cards.compact_text(
        f"{len(cards)} evidence card(s) from {source_kind}/{group}/{family}. "
        f"Representative evidence ids: {', '.join(evidence_ids[:8])}. "
        + " ".join(summary_parts),
        max_summary_chars,
    )
    return evidence_cards.normalize_card(
        {
            "id": f"compacted:{source_kind}:{_safe_id(group)}:{_safe_id(family)}:{evidence_cards.stable_hash(evidence_ids)[:12]}",
            "source_kind": source_kind,
            "title": f"{source_kind} {group} {family}".strip(),
            "summary": summary,
            "source_uri": f"{group}/{family}".strip("/"),
            "confidence": "medium",
            "terms": terms,
            "code_anchors": code_anchors,
            "compacted_evidence_ids": evidence_ids,
            "compacted_source_count": len(cards),
        }
    )


def compact_source_evidence_cards(
    cards: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    compaction_config = dict(config.get("evidence_compaction") or {})
    enabled = bool(compaction_config.get("enabled", True))
    max_raw = max(1, int(compaction_config.get("max_raw_cards_per_source_group", 160) or 160))
    max_compacted = max(1, int(compaction_config.get("max_compacted_cards_per_group", 24) or 24))
    max_summary_chars = max(1, int(config.get("max_summary_chars", 1800) or 1800))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for card in _dedupe_cards(cards):
        grouped[(str(card.get("source_kind") or "generated-note"), _source_group(card))].append(card)

    compacted_cards: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    for (source_kind, group), grouped_cards in sorted(grouped.items()):
        if not enabled or len(grouped_cards) <= max_raw:
            compacted_cards.extend(grouped_cards)
            groups.append(
                {
                    "source_kind": source_kind,
                    "group": group,
                    "raw_card_count": len(grouped_cards),
                    "compacted_card_count": len(grouped_cards),
                    "mode": "raw",
                }
            )
            continue

        family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for card in grouped_cards:
            family_groups[_path_family(card)].append(card)
        ranked_families = sorted(
            family_groups.items(),
            key=lambda item: (-len(item[1]), -sum(_salience_score(card) for card in item[1]), item[0]),
        )
        selected_families = ranked_families[:max_compacted]
        for family, family_cards in selected_families:
            compacted_cards.append(
                _compact_card_family(
                    source_kind=source_kind,
                    group=group,
                    family=family,
                    cards=family_cards,
                    max_summary_chars=max_summary_chars,
                )
            )
        groups.append(
            {
                "source_kind": source_kind,
                "group": group,
                "raw_card_count": len(grouped_cards),
                "family_count": len(family_groups),
                "selected_family_count": len(selected_families),
                "compacted_card_count": len(selected_families),
                "mode": "compacted",
                "omitted_family_count": max(0, len(family_groups) - len(selected_families)),
            }
        )

    soft_call_target = max(1, int(compaction_config.get("max_reducer_gpt_calls_per_layer_soft", 80) or 80))
    inventory = {
        "schema_version": REDUCER_SCHEMA_VERSION,
        "enabled": enabled,
        "raw_card_count": len(cards),
        "deduped_card_count": sum(group["raw_card_count"] for group in groups),
        "compacted_card_count": len(compacted_cards),
        "source_kind_counts_before": evidence_cards.source_kind_counts(cards),
        "source_kind_counts_after": evidence_cards.source_kind_counts(compacted_cards),
        "max_raw_cards_per_source_group": max_raw,
        "max_compacted_cards_per_group": max_compacted,
        "max_reducer_gpt_calls_per_layer_soft": soft_call_target,
        "groups": groups,
    }
    projected_specs = _source_shard_specs(compacted_cards, config) if compacted_cards else []
    inventory["estimated_source_reducer_calls"] = len(projected_specs)
    inventory["soft_target_exceeded"] = len(projected_specs) > soft_call_target
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "source_compaction.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence_cards.stable_cards(compacted_cards), inventory


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        raise SystemExit("Shard size must be positive.")
    return [items[index : index + size] for index in range(0, len(items), size)]


def _source_shard_specs(cards: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        grouped[(str(card.get("source_kind") or "generated-note"), _source_group(card))].append(card)
    specs: list[dict[str, Any]] = []
    max_cards = int(config["max_cards_per_source_shard"])
    for (source_kind, group), grouped_cards in sorted(grouped.items()):
        for index, chunk in enumerate(_chunks(grouped_cards, max_cards), start=1):
            shard_id = f"source-{_safe_id(source_kind)}-{_safe_id(group)}-{index:04d}"
            specs.append(
                {
                    "id": shard_id,
                    "layer": "source",
                    "source_kind": source_kind,
                    "group": group,
                    "cards": chunk,
                    "input_count": len(chunk),
                }
            )
    return specs


def _summary_cards(items: list[dict[str, Any]], *, layer: str, max_summary_chars: int) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in items:
        if item.get("status") != "succeeded":
            continue
        cards.append(
            evidence_cards.normalize_card(
                {
                    "id": f"reducer-summary:{layer}:{item.get('id')}",
                    "source_kind": "reducer-summary",
                    "title": item.get("theme") or item.get("id"),
                    "summary": evidence_cards.compact_text(item.get("summary") or item.get("business_value") or "", max_summary_chars),
                    "source_uri": item.get("id") or "",
                    "confidence": item.get("confidence") or "medium",
                    "terms": item.get("capability_candidates") or item.get("workflow_candidates") or [],
                    "code_anchors": item.get("code_surfaces") or [],
                }
            )
        )
    return evidence_cards.stable_cards(cards)


def _theme_shard_specs(source_results: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    cards = _summary_cards(source_results, layer="source", max_summary_chars=int(config["max_summary_chars"]))
    specs: list[dict[str, Any]] = []
    for index, chunk in enumerate(_chunks(cards, int(config["max_cards_per_theme_shard"])), start=1):
        specs.append({"id": f"theme-{index:04d}", "layer": "theme", "cards": chunk, "input_count": len(chunk)})
    return specs


def _capability_shard_specs(theme_results: list[dict[str, Any]], capabilities: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    cards = _summary_cards(theme_results, layer="theme", max_summary_chars=int(config["max_summary_chars"]))
    if not capabilities:
        capabilities = [{"key": "product", "title": "Product Intelligence", "keywords": []}]
    specs: list[dict[str, Any]] = []
    max_cards = int(config["max_theme_summaries_per_capability_shard"])
    for capability in capabilities:
        title = str(capability.get("title") or capability.get("key") or "Capability")
        keywords = {str(item).casefold() for item in capability.get("keywords", []) if str(item).strip()}
        keywords.add(title.casefold())
        matching = [
            card
            for card in cards
            if any(keyword and keyword in f"{card.get('title', '')} {card.get('summary', '')}".casefold() for keyword in keywords)
        ]
        selected = matching or cards
        for index, chunk in enumerate(_chunks(selected, max_cards), start=1):
            specs.append(
                {
                    "id": f"capability-{_safe_id(str(capability.get('key') or title))}-{index:04d}",
                    "layer": "capability",
                    "capability": {"key": capability.get("key"), "title": title},
                    "cards": chunk,
                    "input_count": len(chunk),
                }
            )
    return specs


def _ontology_shard_specs(capability_results: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    cards = _summary_cards(capability_results, layer="capability", max_summary_chars=int(config["max_summary_chars"]))
    max_cards = int(config["max_capability_summaries_for_ontology"])
    return [
        {"id": f"ontology-{index:04d}", "layer": "ontology", "cards": chunk, "input_count": len(chunk)}
        for index, chunk in enumerate(_chunks(cards, max_cards), start=1)
    ]


class OpenAIHierarchicalReducerClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        rate_limiter: rate_limits.WindowRateLimiter | None = None,
        rate_config: dict[str, Any] | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.rate_config = rate_config or {}
        self.rate_limiter = rate_limiter
        self.recorder = rate_limiter.recorder if rate_limiter is not None else rate_limits.RateLimitRecorder()

    def reduce_many(self, specs: list[dict[str, Any]], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for hierarchical evidence reducers.")
        if not specs:
            return {}
        request_body = openai_responses.build_json_response_payload(
            model=model,
            reasoning_effort=reasoning_effort,
            instructions=(
                "You are a Product BASB hierarchical reducer. Use only the compact cards provided. "
                "Return JSON only with an items array. Each item must include id, theme, summary, "
                "source_kind_counts, evidence_ids, confidence, business_value, workflow_candidates, "
                "capability_candidates, risks, limitations, and code_surfaces. Keep summaries concise "
                "and cite evidence_ids exactly."
            ),
            user_content=json.dumps(
                {
                    "prompt_version": REDUCER_PROMPT_VERSION,
                    "shards": [
                        {
                            "id": spec.get("id"),
                            "layer": spec.get("layer"),
                            "source_kind": spec.get("source_kind"),
                            "group": spec.get("group"),
                            "capability": spec.get("capability"),
                            "cards": spec.get("cards", []),
                        }
                        for spec in specs
                    ],
                },
                sort_keys=True,
            ),
        )
        payload = json.dumps(request_body).encode("utf-8")
        if self.rate_limiter is not None:
            self.rate_limiter.acquire_openai(
                stage=f"{specs[0].get('layer', 'hierarchical')}_reducer",
                worker_count=worker_count,
                tokens=max(1, len(payload) // 4),
                recommended_knob="max_concurrent_openai_reducers",
            )
        request = urllib.request.Request(
            openai_responses.OPENAI_RESPONSES_URL,
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        timeout_seconds = float(self.rate_config.get("fail_fast_seconds") or 120.0)
        stage = f"{specs[0].get('layer', 'hierarchical')}_reducer"
        provider_headers: dict[str, Any] = {}

        def send_request() -> dict[str, Any]:
            nonlocal provider_headers
            try:
                with openai_requests.urlopen(request, timeout=timeout_seconds, opener=urllib.request.urlopen) as response:
                    raw_response = json.loads(response.read().decode("utf-8"))
                    provider_headers = rate_limits.parse_provider_rate_limit_headers(response.headers)
                    if self.rate_limiter is not None:
                        self.rate_limiter.observe_openai_response_headers(
                            response.headers,
                            stage=stage,
                            worker_count=worker_count,
                            recommended_knob="max_concurrent_openai_reducers",
                        )
                    return raw_response
            except HTTPError as exc:
                provider_error = rate_limits.provider_rate_limit_from_http_error(exc)
                if provider_error is not None:
                    raise provider_error from exc
                raise

        raw, retry_count, wait_seconds = rate_limits.with_retries(
            action=send_request,
            config=self.rate_config,
            recorder=self.recorder,
            stage=stage,
            worker_count=worker_count,
            recommended_knob="max_concurrent_openai_reducers",
        )
        parsed = openai_responses.parse_json_response(raw)
        items = parsed.get("items")
        if not isinstance(items, list):
            raise ValueError("OpenAI hierarchical reducer response must include an items array.")
        results: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            results[str(item["id"])] = item
        unmatched_items = [
            item
            for item in items
            if isinstance(item, dict) and str(item.get("id") or "") not in {str(spec["id"]) for spec in specs}
        ]
        for spec in specs:
            expected_id = str(spec["id"])
            if expected_id in results or not unmatched_items:
                continue
            results[expected_id] = {**unmatched_items.pop(0), "id": expected_id}
        missing = [str(spec["id"]) for spec in specs if str(spec["id"]) not in results]
        if missing:
            raise ValueError(f"OpenAI hierarchical reducer response missing ids: {', '.join(missing[:8])}")
        results["__meta__"] = {
            "retry_count": retry_count,
            "rate_limit_wait_seconds": round(wait_seconds, 4),
            "provider_headers": provider_headers,
        }
        return results

    def reduce(self, spec: dict[str, Any], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, Any]:
        return self.reduce_many([spec], model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)[str(spec["id"])]


class FixtureHierarchicalReducerClient:
    def __init__(self, *, fail_layers: set[str] | None = None) -> None:
        self.fail_layers = fail_layers or set()

    def reduce(self, spec: dict[str, Any], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, Any]:
        del model, reasoning_effort, worker_count
        layer = str(spec.get("layer") or "source")
        if layer in self.fail_layers:
            raise RuntimeError(f"fixture failure for {layer}")
        cards = [card for card in spec.get("cards", []) if isinstance(card, dict)]
        title = str(spec.get("source_kind") or spec.get("group") or (spec.get("capability") or {}).get("title") or layer).replace("-", " ").title()
        source_counts = evidence_cards.source_kind_counts(cards)
        evidence_ids = [str(card.get("id")) for card in cards[:40] if card.get("id")]
        terms = sorted({term for card in cards for term in card.get("terms", []) if str(term).strip()})[:12]
        return {
            "theme": f"{title} {layer.title()} Summary",
            "summary": f"{len(cards)} compact evidence card(s) summarize {title} for the {layer} reducer.",
            "source_kind_counts": source_counts,
            "evidence_ids": evidence_ids,
            "confidence": "high" if cards else "low",
            "business_value": f"{title} evidence supports product understanding and shippable work.",
            "workflow_candidates": terms[:6] or [title],
            "capability_candidates": terms[:6] or [title],
            "risks": [],
            "limitations": [] if cards else ["No usable cards reached this reducer."],
            "code_surfaces": [anchor for card in cards for anchor in card.get("code_anchors", [])][:12],
        }

    def reduce_many(self, specs: list[dict[str, Any]], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, dict[str, Any]]:
        return {
            str(spec["id"]): {"id": spec["id"], **self.reduce(spec, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)}
            for spec in specs
        }


def reducer_client(
    *,
    rate_limiter: rate_limits.WindowRateLimiter | None = None,
    rate_config: dict[str, Any] | None = None,
) -> OpenAIHierarchicalReducerClient | FixtureHierarchicalReducerClient:
    if os.environ.get("PRODUCT_BASB_HIERARCHICAL_REDUCER_FIXTURE") == "1" or os.environ.get("PRODUCT_BASB_LLM_FIXTURE") == "1":
        return FixtureHierarchicalReducerClient()
    return OpenAIHierarchicalReducerClient(rate_limiter=rate_limiter, rate_config=rate_config)


def _normalise_reducer_response(spec: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    cards = [card for card in spec.get("cards", []) if isinstance(card, dict)]
    source_counts = response.get("source_kind_counts") if isinstance(response.get("source_kind_counts"), dict) else evidence_cards.source_kind_counts(cards)
    evidence_ids = response.get("evidence_ids")
    if not isinstance(evidence_ids, list):
        evidence_ids = [card.get("id") for card in cards[:40] if card.get("id")]
    return {
        "id": spec["id"],
        "layer": spec["layer"],
        "status": "succeeded",
        "source_kind": spec.get("source_kind"),
        "group": spec.get("group"),
        "capability": spec.get("capability"),
        "input_count": int(spec.get("input_count", len(cards)) or 0),
        "theme": evidence_cards.compact_text(response.get("theme") or spec["id"], 220),
        "summary": evidence_cards.compact_text(response.get("summary") or "", 1800),
        "source_kind_counts": {str(key): int(value) for key, value in source_counts.items() if isinstance(value, (int, float))},
        "evidence_ids": [str(item) for item in evidence_ids[:80] if str(item).strip()],
        "confidence": str(response.get("confidence") or "medium"),
        "business_value": evidence_cards.compact_text(response.get("business_value") or "", 1200),
        "workflow_candidates": [str(item) for item in (response.get("workflow_candidates") or [])[:20] if str(item).strip()],
        "capability_candidates": [str(item) for item in (response.get("capability_candidates") or [])[:20] if str(item).strip()],
        "risks": [str(item) for item in (response.get("risks") or [])[:20] if str(item).strip()],
        "limitations": [str(item) for item in (response.get("limitations") or [])[:20] if str(item).strip()],
        "code_surfaces": [str(item) for item in (response.get("code_surfaces") or [])[:24] if str(item).strip()],
    }


def _stable_reducer_spec(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": REDUCER_SCHEMA_VERSION,
        "layer": spec.get("layer"),
        "id": spec.get("id"),
        "source_kind": spec.get("source_kind"),
        "group": spec.get("group"),
        "capability": spec.get("capability"),
        "input_count": spec.get("input_count"),
        "cards": evidence_cards.stable_cards([card for card in spec.get("cards", []) if isinstance(card, dict)]),
    }


def _cache_key(spec: dict[str, Any], *, model: str, reasoning_effort: str) -> str:
    stable_spec = _stable_reducer_spec(spec)
    return incremental_cache.stable_hash(
        {
            "schema_version": REDUCER_SCHEMA_VERSION,
            "prompt_version": REDUCER_PROMPT_VERSION,
            "layer": stable_spec.get("layer"),
            "id": stable_spec.get("id"),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "payload_hash": incremental_cache.stable_hash(stable_spec),
        }
    )


class ReducerEventRecorder:
    def __init__(self, output_dir: Path, *, enabled: bool) -> None:
        self.path = output_dir / "reducer_events.json"
        self.enabled = enabled
        self.lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.summary: dict[str, Any] = {
            "schema_version": REDUCER_SCHEMA_VERSION,
            "event_count": 0,
            "active_batches": 0,
            "status_counts": {},
            "slowest_call": None,
            "events": [],
        }

    def record(self, **event: Any) -> None:
        if not self.enabled:
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = {"observed_at": now, **event}
        with self.lock:
            self.events.append(payload)
            status_counts = Counter(str(item.get("status") or item.get("event") or "unknown") for item in self.events)
            running = sum(1 for item in self.events if item.get("status") == "running") - sum(
                1 for item in self.events if item.get("event") in {"batch_succeeded", "batch_failed", "batch_split", "cache_hit"}
            )
            completed_calls = [item for item in self.events if isinstance(item.get("elapsed_seconds"), (int, float))]
            slowest = max(completed_calls, key=lambda item: float(item.get("elapsed_seconds") or 0), default=None)
            self.summary = {
                "schema_version": REDUCER_SCHEMA_VERSION,
                "event_count": len(self.events),
                "active_batches": max(0, running),
                "status_counts": dict(status_counts),
                "slowest_call": slowest,
                "events": self.events[-200:],
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    def events_snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.events)

    def finalize(self, **updates: Any) -> dict[str, Any]:
        if not self.enabled:
            return self.summary
        with self.lock:
            self.summary = {**self.summary, **updates, "events": self.events[-200:]}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
            return dict(self.summary)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 4)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(ordered[int(rank)], 4)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 4)


def _exception_kind(exc: BaseException) -> str:
    text = str(exc).casefold()
    if any(marker in text for marker in ("timeout", "timed out", "deadline", "fail_fast")):
        return "timeout"
    if any(marker in text for marker in ("json", "malformed", "items array", "missing ids", "unexpected")):
        return "malformed_response"
    return "error"


def _batch_metrics_from_events(
    events: list[dict[str, Any]],
    *,
    configured_batch_size: int,
    pending_shard_count: int,
    gpt_call_count: int,
) -> dict[str, Any]:
    batch_started = [event for event in events if event.get("event") == "batch_started"]
    completed_events = [
        event
        for event in events
        if event.get("event") in {"batch_succeeded", "batch_failed", "batch_split"}
        and isinstance(event.get("elapsed_seconds"), (int, float))
    ]
    batch_sizes = Counter(str(int(event.get("batch_size") or len(event.get("shard_ids") or []) or 1)) for event in batch_started)
    split_events = [event for event in events if event.get("event") == "batch_split"]
    failed_events = [event for event in events if event.get("event") == "batch_failed"]
    timeout_events = [
        event
        for event in [*split_events, *failed_events]
        if str(event.get("failure_kind") or "").casefold() == "timeout"
    ]
    malformed_events = [
        event
        for event in [*split_events, *failed_events]
        if str(event.get("failure_kind") or "").casefold() == "malformed_response"
    ]
    latencies = [float(event["elapsed_seconds"]) for event in completed_events]
    baseline_calls = math.ceil(max(0, pending_shard_count) / 4) if pending_shard_count else 0
    return {
        "configured_batch_size": configured_batch_size,
        "effective_batch_sizes": dict(sorted(batch_sizes.items(), key=lambda item: int(item[0]))),
        "split_count": len(split_events),
        "timeout_count": len(timeout_events),
        "malformed_response_count": len(malformed_events),
        "p50_elapsed_seconds": _percentile(latencies, 0.50),
        "p95_elapsed_seconds": _percentile(latencies, 0.95),
        "gpt_call_count_saved_vs_batch_size_4": max(0, baseline_calls - int(gpt_call_count or 0)),
        "baseline_gpt_call_count_at_batch_size_4": baseline_calls,
    }


def _provider_remaining_ratios(events: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    request_ratios: list[float] = []
    token_ratios: list[float] = []
    for event in events:
        headers = event.get("provider_headers")
        if not isinstance(headers, dict):
            continue
        limit_requests = headers.get("limit_requests")
        remaining_requests = headers.get("remaining_requests")
        if isinstance(limit_requests, int) and limit_requests > 0 and isinstance(remaining_requests, int):
            request_ratios.append(max(0.0, min(1.0, remaining_requests / limit_requests)))
        limit_tokens = headers.get("limit_tokens")
        remaining_tokens = headers.get("remaining_tokens")
        if isinstance(limit_tokens, int) and limit_tokens > 0 and isinstance(remaining_tokens, int):
            token_ratios.append(max(0.0, min(1.0, remaining_tokens / limit_tokens)))
    return request_ratios, token_ratios


def reducer_concurrency_recommendation(
    *,
    current_max_concurrent_openai_reducers: int,
    batch_metrics: dict[str, Any],
    reducer_events: list[dict[str, Any]],
    rate_limit_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rate_limit_events = list(rate_limit_events or [])
    provider_retry_after_count = sum(1 for event in rate_limit_events if event.get("event") == "provider_retry_after")
    request_ratios, token_ratios = _provider_remaining_ratios(reducer_events)
    provider_headers_observed = bool(request_ratios or token_ratios)
    min_request_remaining = min(request_ratios) if request_ratios else None
    min_token_remaining = min(token_ratios) if token_ratios else None
    split_count = int(batch_metrics.get("split_count") or 0)
    timeout_count = int(batch_metrics.get("timeout_count") or 0)
    malformed_response_count = int(batch_metrics.get("malformed_response_count") or 0)
    p50 = batch_metrics.get("p50_elapsed_seconds")
    p95 = batch_metrics.get("p95_elapsed_seconds")
    recommended = current_max_concurrent_openai_reducers
    reason = "provider headers unavailable; keep explicit reducer concurrency unchanged"
    can_raise = (
        provider_headers_observed
        and provider_retry_after_count == 0
        and split_count == 0
        and timeout_count == 0
        and malformed_response_count == 0
        and (min_request_remaining is None or min_request_remaining > 0.35)
        and (min_token_remaining is None or min_token_remaining > 0.35)
    )
    stable_latency = (
        isinstance(p50, (int, float))
        and isinstance(p95, (int, float))
        and float(p95) <= 45.0
        and float(p95) <= max(1.0, float(p50) * 2.5)
    )
    if can_raise and stable_latency:
        recommended = max(current_max_concurrent_openai_reducers, 48)
        reason = "provider headroom and stable reducer latency support testing 48 concurrent reducers"
    elif can_raise:
        recommended = max(current_max_concurrent_openai_reducers, 36)
        reason = "provider headroom supports testing 36 concurrent reducers"
    elif provider_headers_observed:
        reason = "provider throttling, low remaining capacity, or batch splits occurred; keep concurrency unchanged"
    return {
        "current_max_concurrent_openai_reducers": current_max_concurrent_openai_reducers,
        "recommended_max_concurrent_openai_reducers": recommended,
        "reason": reason,
        "provider_headers_observed": provider_headers_observed,
        "provider_retry_after_count": provider_retry_after_count,
        "min_provider_remaining_request_ratio": round(min_request_remaining, 4) if min_request_remaining is not None else None,
        "min_provider_remaining_token_ratio": round(min_token_remaining, 4) if min_token_remaining is not None else None,
        "stable_latency": stable_latency,
    }


def _partial_result(spec: dict[str, Any], layer: str, exc: Exception) -> dict[str, Any]:
    return {
        "id": spec["id"],
        "layer": spec["layer"],
        "status": "partial",
        "source_kind": spec.get("source_kind"),
        "group": spec.get("group"),
        "capability": spec.get("capability"),
        "input_count": int(spec.get("input_count", 0) or 0),
        "theme": spec["id"],
        "summary": "",
        "source_kind_counts": evidence_cards.source_kind_counts(spec.get("cards", [])),
        "evidence_ids": [str(card.get("id")) for card in spec.get("cards", [])[:40] if isinstance(card, dict) and card.get("id")],
        "confidence": "low",
        "business_value": "",
        "workflow_candidates": [],
        "capability_candidates": [],
        "risks": [],
        "limitations": [f"{layer} reducer failed: {str(exc)[:240]}"],
        "code_surfaces": [],
        "failure_reason": str(exc)[:500],
    }


def _run_layer(
    *,
    layer: str,
    specs: list[dict[str, Any]],
    cache: dict[str, Any] | None,
    client: Any,
    model: str,
    reasoning_effort: str,
    worker_count: int,
    force: bool,
    progress_callback: Callable[[str, int, int], None] | None,
    batch_size: int = 1,
    split_on_timeout: bool = True,
    event_recorder: ReducerEventRecorder | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    stats = {
        "layer": layer,
        "input_shards": len(specs),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_miss_reasons": {},
        "gpt_call_count": 0,
        "batch_count": 0,
        "configured_batch_size": max(1, int(batch_size or 1)),
        "failed": 0,
    }
    results: list[dict[str, Any]] = []
    pending: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    cache_lock = threading.Lock() if cache is not None else None
    completed = 0
    for spec in specs:
        cache_key = _cache_key(spec, model=model, reasoning_effort=reasoning_effort)
        stable_spec = _stable_reducer_spec(spec)
        cache_input = {
            "prompt_version": REDUCER_PROMPT_VERSION,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "spec": stable_spec,
        }
        cached = None
        if not force and cache is not None:
            assert cache_lock is not None
            with cache_lock:
                cached = incremental_cache.lookup(cache, REDUCER_CACHE_NAMESPACE, cache_key, cache_input, dependencies=stable_spec)
        if cached is not None:
            stats["cache_hits"] += 1
            results.append({**dict(cached.value), "cache_hit": True})
            if event_recorder is not None:
                event_recorder.record(
                    event="cache_hit",
                    status="cache_hit",
                    layer=layer,
                    shard_ids=[str(spec.get("id"))],
                    input_card_count=int(spec.get("input_count", 0) or 0),
                )
            completed += 1
            if progress_callback is not None:
                progress_callback(layer, completed, max(1, len(specs)))
        else:
            stats["cache_misses"] += 1
            reason = "forced" if force else "new_or_changed"
            stats["cache_miss_reasons"][reason] = int(stats["cache_miss_reasons"].get(reason, 0)) + 1
            pending.append((spec, cache_key, cache_input))

    def run_batch(batch: list[tuple[dict[str, Any], str, dict[str, Any]]]) -> tuple[list[dict[str, Any]], int]:
        specs_batch = [item[0] for item in batch]
        shard_ids = [str(spec.get("id")) for spec in specs_batch]
        payload_size = len(json.dumps([_stable_reducer_spec(spec) for spec in specs_batch], sort_keys=True, default=str).encode("utf-8"))
        batch_started = time.perf_counter()
        if event_recorder is not None:
            event_recorder.record(
                event="batch_started",
                status="running",
                layer=layer,
                shard_ids=shard_ids,
                batch_size=len(batch),
                input_card_count=sum(int(spec.get("input_count", 0) or 0) for spec in specs_batch),
                payload_bytes=payload_size,
                model=model,
                reasoning_effort=reasoning_effort,
            )
        try:
            if hasattr(client, "reduce_many"):
                responses = client.reduce_many(specs_batch, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)
            else:
                responses = {
                    str(spec["id"]): client.reduce(spec, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)
                    for spec in specs_batch
                }
            response_meta = {}
            if isinstance(responses, dict) and isinstance(responses.get("__meta__"), dict):
                response_meta = dict(responses.pop("__meta__"))
            normalized_results: list[dict[str, Any]] = []
            for spec, cache_key, cache_input in batch:
                result = _normalise_reducer_response(spec, responses[str(spec["id"])])
                normalized_results.append(result)
                if cache is not None:
                    assert cache_lock is not None
                    with cache_lock:
                        incremental_cache.store(
                            cache,
                            REDUCER_CACHE_NAMESPACE,
                            cache_key,
                            cache_input,
                            result,
                            dependencies=_stable_reducer_spec(spec),
                        )
            if event_recorder is not None:
                event_recorder.record(
                    event="batch_succeeded",
                    status="succeeded",
                    layer=layer,
                    shard_ids=shard_ids,
                    batch_size=len(batch),
                    elapsed_seconds=round(time.perf_counter() - batch_started, 4),
                    payload_bytes=payload_size,
                    retry_count=response_meta.get("retry_count", 0),
                    rate_limit_wait_seconds=response_meta.get("rate_limit_wait_seconds", 0.0),
                    provider_headers=response_meta.get("provider_headers", {}),
                )
            return normalized_results, 1
        except Exception as exc:
            failure_kind = _exception_kind(exc)
            if split_on_timeout and len(batch) > 1:
                if event_recorder is not None:
                    event_recorder.record(
                        event="batch_split",
                        status="split",
                        layer=layer,
                        shard_ids=shard_ids,
                        batch_size=len(batch),
                        elapsed_seconds=round(time.perf_counter() - batch_started, 4),
                        payload_bytes=payload_size,
                        failure_kind=failure_kind,
                        reason=str(exc)[:300],
                    )
                split_results: list[dict[str, Any]] = []
                gpt_calls = 1
                for item in batch:
                    item_results, item_calls = run_batch([item])
                    split_results.extend(item_results)
                    gpt_calls += item_calls
                return split_results, gpt_calls
            if event_recorder is not None:
                event_recorder.record(
                    event="batch_failed",
                    status="failed",
                    layer=layer,
                    shard_ids=shard_ids,
                    batch_size=len(batch),
                    elapsed_seconds=round(time.perf_counter() - batch_started, 4),
                    payload_bytes=payload_size,
                    failure_kind=failure_kind,
                    reason=str(exc)[:500],
                )
            return [_partial_result(spec, layer, exc) for spec in specs_batch], 1

    pending_batches = _chunks(pending, max(1, int(batch_size or 1)))
    stats["batch_count"] = len(pending_batches)
    with ThreadPoolExecutor(max_workers=max(1, min(worker_count, len(pending_batches) or 1)), thread_name_prefix=f"basb-{layer}-reducer") as executor:
        futures = [executor.submit(run_batch, batch) for batch in pending_batches]
        for future in as_completed(futures):
            batch_results, gpt_calls = future.result()
            results.extend(batch_results)
            stats["gpt_call_count"] += gpt_calls
            stats["failed"] += sum(1 for result in batch_results if result.get("status") == "partial")
            completed += len(batch_results)
            if progress_callback is not None:
                progress_callback(layer, completed, max(1, len(specs)))

    results.sort(key=lambda item: str(item.get("id") or ""))
    layer_events = [
        event
        for event in (event_recorder.events_snapshot() if event_recorder is not None else [])
        if event.get("layer") == layer
    ]
    stats.update(
        _batch_metrics_from_events(
            layer_events,
            configured_batch_size=max(1, int(batch_size or 1)),
            pending_shard_count=len(pending),
            gpt_call_count=int(stats.get("gpt_call_count", 0) or 0),
        )
    )
    stats["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    stats["status_counts"] = dict(Counter(str(item.get("status") or "unknown") for item in results))
    return results, stats


def _aggregate_reducer_batch_metrics(
    *,
    layer_stats: dict[str, dict[str, Any]],
    reducer_events: list[dict[str, Any]],
    current_max_concurrent_openai_reducers: int,
    rate_limit_events: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    pending_shard_count = sum(int(stats.get("cache_misses", 0) or 0) for stats in layer_stats.values())
    gpt_call_count = sum(int(stats.get("gpt_call_count", 0) or 0) for stats in layer_stats.values())
    configured_batch_sizes = [
        int(stats.get("configured_batch_size") or 0)
        for stats in layer_stats.values()
        if int(stats.get("configured_batch_size") or 0) > 0
    ]
    configured_batch_size = max(configured_batch_sizes) if configured_batch_sizes else int(DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["batch_size"])
    metrics = _batch_metrics_from_events(
        reducer_events,
        configured_batch_size=configured_batch_size,
        pending_shard_count=pending_shard_count,
        gpt_call_count=gpt_call_count,
    )
    metrics["gpt_call_count"] = gpt_call_count
    metrics["pending_shard_count"] = pending_shard_count
    metrics["timeout_pressure"] = bool(metrics.get("split_count") or metrics.get("timeout_count"))
    metrics["layer_metrics"] = {
        layer: {
            "configured_batch_size": stats.get("configured_batch_size"),
            "effective_batch_sizes": stats.get("effective_batch_sizes", {}),
            "split_count": stats.get("split_count", 0),
            "timeout_count": stats.get("timeout_count", 0),
            "malformed_response_count": stats.get("malformed_response_count", 0),
            "p50_elapsed_seconds": stats.get("p50_elapsed_seconds"),
            "p95_elapsed_seconds": stats.get("p95_elapsed_seconds"),
            "gpt_call_count": stats.get("gpt_call_count", 0),
            "gpt_call_count_saved_vs_batch_size_4": stats.get("gpt_call_count_saved_vs_batch_size_4", 0),
        }
        for layer, stats in layer_stats.items()
    }
    recommendation = reducer_concurrency_recommendation(
        current_max_concurrent_openai_reducers=current_max_concurrent_openai_reducers,
        batch_metrics=metrics,
        reducer_events=reducer_events,
        rate_limit_events=rate_limit_events,
    )
    metrics.update(recommendation)
    return metrics


def _coverage_limitations(*layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limitations: list[dict[str, Any]] = []
    for layer_results in layers:
        for item in layer_results:
            if item.get("status") == "succeeded":
                continue
            limitations.append(
                {
                    "layer": item.get("layer"),
                    "id": item.get("id"),
                    "source_kind": item.get("source_kind"),
                    "reason": "; ".join(item.get("limitations") or [item.get("failure_reason") or "Reducer did not complete."]),
                }
            )
    return limitations


def _ontology_cards(ontology_results: list[dict[str, Any]], capability_results: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    source = [item for item in ontology_results if item.get("status") == "succeeded"] or [
        item for item in capability_results if item.get("status") == "succeeded"
    ]
    cards = [
        {
            "id": f"reducer-summary:ontology:{item.get('id')}",
            "source_kind": "reducer-summary",
            "title": item.get("theme") or item.get("id"),
            "summary": " ".join(str(value) for value in [item.get("summary"), item.get("business_value")] if str(value).strip()),
            "source_uri": str(item.get("id") or ""),
            "confidence": item.get("confidence") or "medium",
            "terms": [*item.get("workflow_candidates", []), *item.get("capability_candidates", [])],
            "code_anchors": item.get("code_surfaces") or [],
        }
        for item in source
    ]
    return evidence_cards.stable_cards(cards, limit=int(config["max_capability_summaries_for_ontology"]))


def run_hierarchical_reducers(
    *,
    cards: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
    evidence_config: dict[str, Any],
    generation_config: dict[str, Any],
    business_config: dict[str, Any],
    cache: dict[str, Any] | None,
    output_dir: Path,
    rate_limiter: rate_limits.WindowRateLimiter | None = None,
    rate_limit_config: dict[str, Any] | None = None,
    force: bool = False,
    client: Any | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    include_generated = bool(evidence_config.get("generated_notes_feed_synthesis", False))
    bounded_cards = _bounded_cards(
        cards,
        max_summary_chars=int(evidence_config["max_summary_chars"]),
        include_generated_notes=include_generated,
    )
    if not bounded_cards:
        raise SystemExit("No usable evidence cards reached hierarchical reducers; cannot synthesize Product Ontology v2.")
    output_dir.mkdir(parents=True, exist_ok=True)
    reducer_config = dict(evidence_config.get("hierarchical_reducers") or {})
    batch_size = max(1, int(reducer_config.get("batch_size", 1) or 1))
    split_on_timeout = bool(reducer_config.get("split_on_timeout", True))
    event_recorder = ReducerEventRecorder(
        output_dir,
        enabled=bool(reducer_config.get("live_events_enabled", True)),
    )
    bounded_cards, compaction_inventory = compact_source_evidence_cards(
        bounded_cards,
        config=evidence_config,
        output_dir=output_dir,
    )
    active_client = client or reducer_client(rate_limiter=rate_limiter, rate_config=rate_limit_config)
    model = str(business_config.get("llm_model") or openai_responses.DEFAULT_REASONING_MODEL)
    source_reasoning_effort = openai_responses.normalize_reasoning_effort(
        reducer_config.get(
            "source_reasoning_effort",
            DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["source_reasoning_effort"],
        )
    )
    theme_reasoning_effort = openai_responses.normalize_reasoning_effort(
        reducer_config.get(
            "theme_reasoning_effort",
            DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["theme_reasoning_effort"],
        )
    )
    capability_reasoning_effort = openai_responses.normalize_reasoning_effort(
        reducer_config.get(
            "capability_reasoning_effort",
            DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["capability_reasoning_effort"],
        )
    )
    ontology_reasoning_effort = openai_responses.normalize_reasoning_effort(
        reducer_config.get(
            "ontology_reasoning_effort",
            business_config.get("ontology_reasoning_effort", DEFAULT_EVIDENCE_SCALING["hierarchical_reducers"]["ontology_reasoning_effort"]),
        )
    )
    max_openai_reducers = max(1, int(generation_config.get("max_concurrent_openai_reducers", 24) or 24))
    source_specs = _source_shard_specs(bounded_cards, evidence_config)
    source_results, source_stats = _run_layer(
        layer="source_shards",
        specs=source_specs,
        cache=cache,
        client=active_client,
        model=model,
        reasoning_effort=source_reasoning_effort,
        worker_count=min(max_openai_reducers, int(generation_config.get("source_shard_workers", 40))),
        force=force,
        progress_callback=progress_callback,
        batch_size=batch_size,
        split_on_timeout=split_on_timeout,
        event_recorder=event_recorder,
    )
    if not any(item.get("status") == "succeeded" for item in source_results):
        raise SystemExit("All source reducers failed; cannot synthesize Product Ontology v2.")

    theme_specs = _theme_shard_specs(source_results, evidence_config)
    theme_results, theme_stats = _run_layer(
        layer="theme_reducers",
        specs=theme_specs,
        cache=cache,
        client=active_client,
        model=model,
        reasoning_effort=theme_reasoning_effort,
        worker_count=min(max_openai_reducers, int(generation_config.get("theme_reducer_workers", 24))),
        force=force,
        progress_callback=progress_callback,
        batch_size=batch_size,
        split_on_timeout=split_on_timeout,
        event_recorder=event_recorder,
    )
    capability_specs = _capability_shard_specs(theme_results, capabilities, evidence_config)
    capability_results, capability_stats = _run_layer(
        layer="capability_reducers",
        specs=capability_specs,
        cache=cache,
        client=active_client,
        model=model,
        reasoning_effort=capability_reasoning_effort,
        worker_count=min(max_openai_reducers, int(generation_config.get("capability_reducer_workers", 16))),
        force=force,
        progress_callback=progress_callback,
        batch_size=batch_size,
        split_on_timeout=split_on_timeout,
        event_recorder=event_recorder,
    )
    ontology_specs = _ontology_shard_specs(capability_results, evidence_config)
    ontology_results, ontology_stats = _run_layer(
        layer="ontology_reducer",
        specs=ontology_specs,
        cache=cache,
        client=active_client,
        model=model,
        reasoning_effort=ontology_reasoning_effort,
        worker_count=min(max_openai_reducers, int(generation_config.get("ontology_reducer_workers", 4))),
        force=force,
        progress_callback=progress_callback,
        batch_size=batch_size,
        split_on_timeout=split_on_timeout,
        event_recorder=event_recorder,
    )
    if not any(item.get("status") == "succeeded" for item in ontology_results):
        raise SystemExit("All ontology reducers failed; cannot synthesize Product Ontology v2.")

    source_inventory = {"schema_version": REDUCER_SCHEMA_VERSION, "stats": source_stats, "shards": source_results}
    theme_inventory = {"schema_version": REDUCER_SCHEMA_VERSION, "stats": theme_stats, "shards": theme_results}
    capability_inventory = {"schema_version": REDUCER_SCHEMA_VERSION, "stats": capability_stats, "shards": capability_results}
    ontology_inventory = {"schema_version": REDUCER_SCHEMA_VERSION, "stats": ontology_stats, "shards": ontology_results}
    coverage_limitations = _coverage_limitations(source_results, theme_results, capability_results, ontology_results)
    evidence_graph = {
        "schema_version": REDUCER_SCHEMA_VERSION,
        "generated_notes_feed_synthesis": include_generated,
        "source_kind_counts": evidence_cards.source_kind_counts(bounded_cards),
        "source_card_count": len(bounded_cards),
        "raw_source_card_count": compaction_inventory.get("raw_card_count", len(cards)),
        "source_compaction": {
            "enabled": compaction_inventory.get("enabled", False),
            "raw_card_count": compaction_inventory.get("raw_card_count", len(cards)),
            "compacted_card_count": compaction_inventory.get("compacted_card_count", len(bounded_cards)),
            "estimated_source_reducer_calls": compaction_inventory.get("estimated_source_reducer_calls"),
            "soft_target_exceeded": compaction_inventory.get("soft_target_exceeded", False),
        },
        "source_cards": bounded_cards,
        "layers": {
            "source_shards": {"count": len(source_results), "status_counts": source_stats["status_counts"]},
            "theme_reducers": {"count": len(theme_results), "status_counts": theme_stats["status_counts"]},
            "capability_reducers": {"count": len(capability_results), "status_counts": capability_stats["status_counts"]},
            "ontology_reducer": {"count": len(ontology_results), "status_counts": ontology_stats["status_counts"]},
        },
        "coverage_limitations": coverage_limitations,
    }
    (output_dir / "evidence_graph.json").write_text(json.dumps(evidence_graph, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "source_shards.json").write_text(json.dumps(source_inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "theme_shards.json").write_text(json.dumps(theme_inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "capability_shards.json").write_text(json.dumps(capability_inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "ontology_reducer.json").write_text(json.dumps(ontology_inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    layer_stats = {
        "source_shards": source_stats,
        "theme_reducers": theme_stats,
        "capability_reducers": capability_stats,
        "ontology_reducer": ontology_stats,
    }
    reducer_events = event_recorder.events_snapshot()
    rate_limit_events = []
    recorder = getattr(rate_limiter, "recorder", None)
    if recorder is not None and hasattr(recorder, "events"):
        rate_limit_events = recorder.events()
    reducer_batch_metrics = _aggregate_reducer_batch_metrics(
        layer_stats=layer_stats,
        reducer_events=reducer_events,
        current_max_concurrent_openai_reducers=max_openai_reducers,
        rate_limit_events=rate_limit_events,
    )
    reducer_event_summary = event_recorder.finalize(
        reducer_batch_metrics=reducer_batch_metrics,
        recommended_max_concurrent_openai_reducers=reducer_batch_metrics.get("recommended_max_concurrent_openai_reducers"),
        concurrency_recommendation_reason=reducer_batch_metrics.get("reason"),
    )
    return {
        "schema_version": REDUCER_SCHEMA_VERSION,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "evidence_graph": evidence_graph,
        "source_shards": source_inventory,
        "theme_shards": theme_inventory,
        "capability_shards": capability_inventory,
        "ontology_reducer": ontology_inventory,
        "ontology_evidence_cards": _ontology_cards(ontology_results, capability_results, evidence_config),
        "coverage_limitations": coverage_limitations,
        "reasoning_efforts": {
            "source_shards": source_reasoning_effort,
            "theme_reducers": theme_reasoning_effort,
            "capability_reducers": capability_reasoning_effort,
            "ontology_reducer": ontology_reasoning_effort,
        },
        "layer_stats": layer_stats,
        "source_compaction": compaction_inventory,
        "reducer_events": reducer_event_summary,
        "reducer_batch_metrics": reducer_batch_metrics,
        "recommended_max_concurrent_openai_reducers": reducer_batch_metrics.get("recommended_max_concurrent_openai_reducers"),
        "concurrency_recommendation_reason": reducer_batch_metrics.get("reason"),
        "cache_hits": sum(int(stats.get("cache_hits", 0) or 0) for stats in layer_stats.values()),
        "cache_misses": sum(int(stats.get("cache_misses", 0) or 0) for stats in layer_stats.values()),
        "gpt_call_count": sum(int(stats.get("gpt_call_count", 0) or 0) for stats in layer_stats.values()),
        "partial_count": len(coverage_limitations),
    }
