#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
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
import rate_limits


DEFAULT_EVIDENCE_SCALING: dict[str, Any] = {
    "generated_notes_feed_synthesis": False,
    "max_cards_per_source_shard": 80,
    "max_cards_per_theme_shard": 80,
    "max_theme_summaries_per_capability_shard": 40,
    "max_capability_summaries_for_ontology": 60,
    "max_summary_chars": 1800,
    "unlimited_total_shards": True,
}

EVIDENCE_SCALING_ENV_OVERRIDES = {
    "generated_notes_feed_synthesis": ("PRODUCT_BASB_GENERATED_NOTES_FEED_SYNTHESIS",),
    "max_cards_per_source_shard": ("PRODUCT_BASB_MAX_CARDS_PER_SOURCE_SHARD",),
    "max_cards_per_theme_shard": ("PRODUCT_BASB_MAX_CARDS_PER_THEME_SHARD",),
    "max_theme_summaries_per_capability_shard": ("PRODUCT_BASB_MAX_THEME_SUMMARIES_PER_CAPABILITY_SHARD",),
    "max_capability_summaries_for_ontology": ("PRODUCT_BASB_MAX_CAPABILITY_SUMMARIES_FOR_ONTOLOGY",),
    "max_summary_chars": ("PRODUCT_BASB_MAX_SUMMARY_CHARS",),
    "unlimited_total_shards": ("PRODUCT_BASB_UNLIMITED_TOTAL_SHARDS",),
}

REDUCER_CACHE_NAMESPACE = "hierarchical_reducers"
REDUCER_PROMPT_VERSION = "product-basb-hierarchical-reducer-v1"
REDUCER_SCHEMA_VERSION = 1


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


def default_evidence_scaling_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("evidence_scaling") or {})
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

    def reduce(self, spec: dict[str, Any], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for hierarchical evidence reducers.")
        request_body = openai_responses.build_json_response_payload(
            model=model,
            reasoning_effort=reasoning_effort,
            instructions=(
                "You are a Product BASB hierarchical reducer. Use only the compact cards provided. "
                "Return JSON only with theme, summary, source_kind_counts, evidence_ids, confidence, "
                "business_value, workflow_candidates, capability_candidates, risks, limitations, and code_surfaces. "
                "Keep summaries concise and cite evidence_ids exactly."
            ),
            user_content=json.dumps(
                {
                    "prompt_version": REDUCER_PROMPT_VERSION,
                    "layer": spec.get("layer"),
                    "shard_id": spec.get("id"),
                    "source_kind": spec.get("source_kind"),
                    "group": spec.get("group"),
                    "capability": spec.get("capability"),
                    "cards": spec.get("cards", []),
                },
                sort_keys=True,
            ),
        )
        payload = json.dumps(request_body).encode("utf-8")
        if self.rate_limiter is not None:
            self.rate_limiter.acquire_openai(
                stage=f"{spec.get('layer', 'hierarchical')}_reducer",
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
        stage = f"{spec.get('layer', 'hierarchical')}_reducer"

        def send_request() -> dict[str, Any]:
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    raw_response = json.loads(response.read().decode("utf-8"))
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

        raw, _retry_count, _wait_seconds = rate_limits.with_retries(
            action=send_request,
            config=self.rate_config,
            recorder=self.recorder,
            stage=stage,
            worker_count=worker_count,
            recommended_knob="max_concurrent_openai_reducers",
        )
        return openai_responses.parse_json_response(raw)


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


def _cache_key(spec: dict[str, Any], *, model: str, reasoning_effort: str) -> str:
    return incremental_cache.stable_hash(
        {
            "schema_version": REDUCER_SCHEMA_VERSION,
            "prompt_version": REDUCER_PROMPT_VERSION,
            "layer": spec.get("layer"),
            "id": spec.get("id"),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "payload_hash": incremental_cache.stable_hash(spec),
        }
    )


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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    stats = {"layer": layer, "input_shards": len(specs), "cache_hits": 0, "cache_misses": 0, "gpt_call_count": 0, "failed": 0}
    results: list[dict[str, Any]] = []
    pending: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    completed = 0
    for spec in specs:
        cache_key = _cache_key(spec, model=model, reasoning_effort=reasoning_effort)
        cache_input = {
            "prompt_version": REDUCER_PROMPT_VERSION,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "spec": spec,
        }
        cached = None if force or cache is None else incremental_cache.lookup(cache, REDUCER_CACHE_NAMESPACE, cache_key, cache_input, dependencies=spec)
        if cached is not None:
            stats["cache_hits"] += 1
            results.append({**dict(cached.value), "cache_hit": True})
            completed += 1
            if progress_callback is not None:
                progress_callback(layer, completed, max(1, len(specs)))
        else:
            stats["cache_misses"] += 1
            pending.append((spec, cache_key, cache_input))

    def run_one(spec: dict[str, Any], cache_key: str, cache_input: dict[str, Any]) -> dict[str, Any]:
        try:
            response = client.reduce(spec, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)
            result = _normalise_reducer_response(spec, response)
            if cache is not None:
                incremental_cache.store(cache, REDUCER_CACHE_NAMESPACE, cache_key, cache_input, result, dependencies=spec)
            return result
        except Exception as exc:
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

    with ThreadPoolExecutor(max_workers=max(1, min(worker_count, len(pending) or 1)), thread_name_prefix=f"basb-{layer}-reducer") as executor:
        futures = [executor.submit(run_one, spec, cache_key, cache_input) for spec, cache_key, cache_input in pending]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result.get("status") == "partial":
                stats["failed"] += 1
            else:
                stats["gpt_call_count"] += 1
            completed += 1
            if progress_callback is not None:
                progress_callback(layer, completed, max(1, len(specs)))

    results.sort(key=lambda item: str(item.get("id") or ""))
    stats["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    stats["status_counts"] = dict(Counter(str(item.get("status") or "unknown") for item in results))
    return results, stats


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
    active_client = client or reducer_client(rate_limiter=rate_limiter, rate_config=rate_limit_config)
    model = str(business_config.get("llm_model") or openai_responses.DEFAULT_REASONING_MODEL)
    reasoning_effort = str(business_config.get("reasoning_effort") or openai_responses.DEFAULT_REASONING_EFFORT)
    max_openai_reducers = max(1, int(generation_config.get("max_concurrent_openai_reducers", 24) or 24))
    source_specs = _source_shard_specs(bounded_cards, evidence_config)
    source_results, source_stats = _run_layer(
        layer="source_shards",
        specs=source_specs,
        cache=cache,
        client=active_client,
        model=model,
        reasoning_effort=reasoning_effort,
        worker_count=min(max_openai_reducers, int(generation_config.get("source_shard_workers", 40))),
        force=force,
        progress_callback=progress_callback,
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
        reasoning_effort=reasoning_effort,
        worker_count=min(max_openai_reducers, int(generation_config.get("theme_reducer_workers", 24))),
        force=force,
        progress_callback=progress_callback,
    )
    capability_specs = _capability_shard_specs(theme_results, capabilities, evidence_config)
    capability_results, capability_stats = _run_layer(
        layer="capability_reducers",
        specs=capability_specs,
        cache=cache,
        client=active_client,
        model=model,
        reasoning_effort=reasoning_effort,
        worker_count=min(max_openai_reducers, int(generation_config.get("capability_reducer_workers", 16))),
        force=force,
        progress_callback=progress_callback,
    )
    ontology_specs = _ontology_shard_specs(capability_results, evidence_config)
    ontology_results, ontology_stats = _run_layer(
        layer="ontology_reducer",
        specs=ontology_specs,
        cache=cache,
        client=active_client,
        model=model,
        reasoning_effort=reasoning_effort,
        worker_count=min(max_openai_reducers, int(generation_config.get("ontology_reducer_workers", 4))),
        force=force,
        progress_callback=progress_callback,
    )
    if not any(item.get("status") == "succeeded" for item in ontology_results):
        raise SystemExit("All ontology reducers failed; cannot synthesize Product Ontology v2.")

    output_dir.mkdir(parents=True, exist_ok=True)
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
        "layer_stats": layer_stats,
        "cache_hits": sum(int(stats.get("cache_hits", 0) or 0) for stats in layer_stats.values()),
        "cache_misses": sum(int(stats.get("cache_misses", 0) or 0) for stats in layer_stats.values()),
        "gpt_call_count": sum(int(stats.get("gpt_call_count", 0) or 0) for stats in layer_stats.values()),
        "partial_count": len(coverage_limitations),
    }
