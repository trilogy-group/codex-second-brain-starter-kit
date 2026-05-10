#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError


OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
LLM_SYNTHESIS_PROMPT_VERSION = "product-basb-cluster-synthesis-v1"

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generation_performance
import rate_limits
import openai_responses
import openai_requests


SEMANTIC_ENV_OVERRIDES = {
    "llm_model": ("PRODUCT_BASB_LLM_MODEL", "TYLER_SECOND_BRAIN_LLM_MODEL"),
    "reasoning_effort": ("PRODUCT_BASB_LLM_REASONING_EFFORT", "TYLER_SECOND_BRAIN_LLM_REASONING_EFFORT"),
}


def _semantic_value(configured: dict[str, Any], field: str, default: Any) -> Any:
    for env_name in SEMANTIC_ENV_OVERRIDES.get(field, ()):
        value = os.environ.get(env_name)
        if value not in (None, ""):
            return value
    return configured.get(field, default)


def _response_headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", {})
    items = headers.items() if hasattr(headers, "items") else []
    return {str(key): str(value) for key, value in items}


def _openai_response_observer(
    limiter: rate_limits.WindowRateLimiter | None,
    *,
    stage: str,
    worker_count: int,
    recommended_knob: str,
) -> Callable[[dict[str, str]], None] | None:
    if limiter is None:
        return None

    def observe(headers: dict[str, str]) -> None:
        limiter.observe_openai_response_headers(
            headers,
            stage=stage,
            worker_count=worker_count,
            recommended_knob=recommended_knob,
        )

    return observe


def default_semantic_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("semantic_clustering") or {})
    generation_config = generation_performance.default_generation_config(profile)
    return {
        "provider": configured.get("provider", "openai"),
        "embedding_model": configured.get("embedding_model", "text-embedding-3-small"),
        "min_cluster_size": int(configured.get("min_cluster_size", 3)),
        "similarity_threshold": float(configured.get("similarity_threshold", 0.78)),
        "max_clusters": int(configured.get("max_clusters", 40)),
        "llm_model": _semantic_value(configured, "llm_model", openai_responses.DEFAULT_REASONING_MODEL),
        "reasoning_effort": _semantic_value(configured, "reasoning_effort", openai_responses.DEFAULT_REASONING_EFFORT),
        "llm_cluster_synthesis": bool(configured.get("llm_cluster_synthesis", True)),
        "max_llm_clusters": int(configured.get("max_llm_clusters", 40)),
        "embedding_workers": generation_config["embedding_workers"],
        "embedding_batch_size": generation_config["embedding_batch_size"],
        "llm_synthesis_workers": generation_config["llm_synthesis_workers"],
    }


def require_openai_or_fixture() -> None:
    if os.environ.get("PRODUCT_BASB_EMBEDDING_FIXTURE") == "1":
        return
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for semantic clustering. Set PRODUCT_BASB_EMBEDDING_FIXTURE=1 only for tests or local smoke fixtures.")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def card_text(card: dict[str, Any]) -> str:
    parts = [
        f"title: {card.get('title', '')}",
        f"kind: {card.get('kind', '')}",
        f"capabilities: {', '.join(card.get('capabilities', []))}",
        f"summary: {card.get('summary', '')}",
        f"evidence: {', '.join(card.get('evidence_terms', []))}",
        f"code: {', '.join(card.get('code_terms', []))}",
    ]
    return normalize_text("\n".join(parts))[:4000]


def content_hash(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}\0{text}".encode("utf-8")).hexdigest()


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


class OpenAIEmbeddingClient:
    def __init__(self, api_key: str | None = None, *, response_observer: Callable[[dict[str, str]], None] | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.response_observer = response_observer

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for semantic clustering.")
        payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            OPENAI_EMBEDDINGS_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with openai_requests.urlopen(request, timeout=600, opener=urllib.request.urlopen) as response:
                data = json.loads(response.read().decode("utf-8"))
                headers = _response_headers(response)
        except HTTPError as exc:
            provider_error = rate_limits.provider_rate_limit_from_http_error(exc)
            if provider_error is not None:
                raise provider_error from exc
            raise
        if self.response_observer is not None:
            self.response_observer(headers)
        return [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]


class OpenAILLMSynthesisClient:
    def __init__(self, api_key: str | None = None, *, response_observer: Callable[[dict[str, str]], None] | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.response_observer = response_observer

    def synthesize_cluster(self, cluster: dict[str, Any], model: str, reasoning_effort: str = openai_responses.DEFAULT_REASONING_EFFORT) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for LLM semantic cluster synthesis.")
        payload = json.dumps(
            openai_responses.build_json_response_payload(
                model=model,
                reasoning_effort=reasoning_effort,
                instructions=(
                    "You name and explain Product BASB intermediate-packet clusters. "
                    "Return JSON only with keys: theme, summary, why_this_cluster_exists, "
                    "merge_split_recommendation, output_candidate_rationale, limitations."
                ),
                user_content=json.dumps(compact_cluster_for_llm(cluster), sort_keys=True),
            )
        ).encode("utf-8")
        request = urllib.request.Request(
            openai_responses.OPENAI_RESPONSES_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with openai_requests.urlopen(request, timeout=60, opener=urllib.request.urlopen) as response:
                data = json.loads(response.read().decode("utf-8"))
                headers = _response_headers(response)
        except HTTPError as exc:
            provider_error = rate_limits.provider_rate_limit_from_http_error(exc)
            if provider_error is not None:
                raise provider_error from exc
            raise
        if self.response_observer is not None:
            self.response_observer(headers)
        return openai_responses.parse_json_response(data)


class FixtureEmbeddingClient:
    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        del model
        vectors: list[list[float]] = []
        themes = [
            {"auth", "login", "session", "sso", "permission", "identity"},
            {"api", "webhook", "schema", "event", "contract", "oauth"},
            {"billing", "invoice", "subscription", "payment", "commerce"},
            {"mobile", "ios", "android", "client", "device"},
            {"report", "analytics", "metric", "dashboard", "insight"},
            {"test", "spec", "coverage", "fixture", "factory"},
            {"deploy", "docker", "ci", "pipeline", "environment", "runtime"},
            {"support", "article", "wiki", "documentation", "runbook"},
        ]
        for text in texts:
            tokens = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
            vector = [float(len(tokens.intersection(theme))) for theme in themes]
            if not any(vector):
                digest = hashlib.sha256(text.encode("utf-8")).digest()
                vector = [float(byte % 17) / 17.0 for byte in digest[: len(themes)]]
            vectors.append(vector)
        return vectors


class FixtureLLMSynthesisClient:
    def synthesize_cluster(self, cluster: dict[str, Any], model: str, reasoning_effort: str = openai_responses.DEFAULT_REASONING_EFFORT) -> dict[str, Any]:
        del model, reasoning_effort
        theme = cluster.get("theme") or theme_for_cards(cluster.get("cards", []))
        return {
            "theme": f"{theme} Synthesized",
            "summary": f"Reusable BASB packet for {theme}.",
            "why_this_cluster_exists": "Fixture synthesis grouped these cards by related product and code evidence.",
            "merge_split_recommendation": "Keep as one packet unless a human reviewer sees unrelated delivery paths.",
            "output_candidate_rationale": "Promote when the linked evidence supports a shippable follow-up.",
            "limitations": [
                "Fixture LLM synthesis was used.",
                "Review source evidence before delivery use.",
            ],
        }


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"items": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"items": {}}
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"items": {}}
    return data


def write_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


def semantic_result_cache_key(cards: list[dict[str, Any]], config: dict[str, Any]) -> str:
    cache_config = {
        key: config.get(key)
        for key in (
            "provider",
            "embedding_model",
            "min_cluster_size",
            "similarity_threshold",
            "max_clusters",
            "llm_model",
            "reasoning_effort",
            "llm_cluster_synthesis",
            "max_llm_clusters",
        )
    }
    return hashlib.sha256(
        json.dumps(
            {
                "cards": cards,
                "config": cache_config,
                "prompt_version": LLM_SYNTHESIS_PROMPT_VERSION,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def embed_cards(
    cards: list[dict[str, Any]],
    config: dict[str, Any],
    cache_path: Path,
    client: Any | None = None,
    limiter: rate_limits.WindowRateLimiter | None = None,
) -> tuple[list[list[float]], dict[str, int]]:
    if client is None:
        require_openai_or_fixture()
    model = str(config["embedding_model"])
    cache = load_cache(cache_path)
    vectors: list[list[float] | None] = [None] * len(cards)
    misses: list[tuple[int, str, str]] = []
    cache_hits = 0
    for index, card in enumerate(cards):
        text = card_text(card)
        key = content_hash(text, model)
        cached = cache["items"].get(key)
        if cached and cached.get("model") == model:
            vectors[index] = cached["embedding"]
            cache_hits += 1
        else:
            misses.append((index, key, text))
    if misses:
        batch_size = int(config.get("embedding_batch_size", 512))
        worker_count = int(config.get("embedding_workers", 8))
        client = client or (
            FixtureEmbeddingClient()
            if os.environ.get("PRODUCT_BASB_EMBEDDING_FIXTURE") == "1"
            else OpenAIEmbeddingClient(
                response_observer=_openai_response_observer(
                    limiter,
                    stage="semantic_embedding",
                    worker_count=worker_count,
                    recommended_knob="embedding_workers",
                )
            )
        )
        miss_batches = chunks(misses, batch_size)
        shared_budget = rate_limits.shared_budget_from_config(config, recorder=limiter.recorder if limiter else None)

        def embed_batch(batch: list[tuple[int, str, str]]) -> list[list[float]]:
            token_count = sum(len(text) for _, _, text in batch) // 4
            if limiter is not None:
                limiter.acquire_openai(
                    stage="semantic_embedding",
                    worker_count=worker_count,
                    tokens=token_count,
                    recommended_knob="embedding_workers",
                )
            if shared_budget is not None:
                shared_budget.acquire(
                    stage="semantic_embedding",
                    worker_count=worker_count,
                    requests=1,
                    tokens=token_count,
                    recommended_knob="embedding_workers",
                )
            return client.embed([text for _, _, text in batch], model)

        try:
            if len(miss_batches) == 1:
                embedded_batches = [embed_batch(miss_batches[0])]
            else:
                with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="basb-embedding") as executor:
                    embedded_batches = list(executor.map(embed_batch, miss_batches))
        except Exception as exc:
            raise SystemExit(
                "OpenAI semantic clustering failed during embedding "
                f"with embedding_workers={worker_count} and embedding_batch_size={batch_size}: {exc}"
            ) from exc
        for batch, embedded in zip(miss_batches, embedded_batches):
            for (index, key, text), vector in zip(batch, embedded):
                vectors[index] = vector
                cache["items"][key] = {
                    "model": model,
                    "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "embedding": vector,
                }
    write_cache(cache_path, cache)
    return [vector or [] for vector in vectors], {"cache_hits": cache_hits, "cache_misses": len(misses), "openai_failures": 0}


def theme_for_cards(cards: list[dict[str, Any]]) -> str:
    weighted: dict[str, int] = {}
    for card in cards:
        for term in [*card.get("capabilities", []), *card.get("evidence_terms", []), *card.get("code_terms", [])]:
            token = normalize_text(str(term)).lower()
            if len(token) >= 3:
                weighted[token] = weighted.get(token, 0) + 1
    if not weighted:
        return "Semantic Evidence Cluster"
    terms = [term.title() for term, _ in sorted(weighted.items(), key=lambda item: (-item[1], item[0]))[:4]]
    return " / ".join(terms)


def compact_cluster_for_llm(cluster: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": cluster.get("id", ""),
        "deterministic_theme": cluster.get("theme", ""),
        "similarity_score": cluster.get("similarity_score", 0),
        "evidence_score": cluster.get("evidence_score", 0),
        "cards": [
            {
                "id": card.get("id", ""),
                "kind": card.get("kind", ""),
                "title": card.get("title", ""),
                "summary": card.get("summary", ""),
                "capabilities": card.get("capabilities", [])[:8],
                "evidence_terms": card.get("evidence_terms", [])[:12],
                "code_terms": card.get("code_terms", [])[:12],
            }
            for card in cluster.get("cards", [])[:20]
        ],
    }


def llm_cache_key(cluster: dict[str, Any], model: str, reasoning_effort: str) -> str:
    card_ids = sorted(str(card_id) for card_id in cluster.get("card_ids", []))
    raw = json.dumps(
        {
            "prompt_version": LLM_SYNTHESIS_PROMPT_VERSION,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "card_ids": card_ids,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def apply_llm_synthesis(cluster: dict[str, Any], synthesis: dict[str, Any], status: str, model: str, reasoning_effort: str) -> dict[str, Any]:
    result = dict(cluster)
    if status == "succeeded":
        if synthesis.get("theme"):
            result["theme"] = str(synthesis["theme"])[:180]
        result["llm_summary"] = str(synthesis.get("summary", "")).strip()
        result["why_this_cluster_exists"] = str(synthesis.get("why_this_cluster_exists", "")).strip()
        result["merge_split_recommendation"] = str(synthesis.get("merge_split_recommendation", "")).strip()
        result["output_candidate_rationale"] = str(synthesis.get("output_candidate_rationale", "")).strip()
        limitations = synthesis.get("limitations", [])
        if isinstance(limitations, str):
            limitations = [limitations]
        result["limitations"] = [str(item) for item in limitations if str(item).strip()] or result.get("limitations", [])
    result["llm_synthesis_status"] = status
    result["llm_model"] = model
    result["llm_reasoning_effort"] = reasoning_effort
    result["llm_prompt_version"] = LLM_SYNTHESIS_PROMPT_VERSION
    return result


def synthesize_clusters_with_llm(
    clusters: list[dict[str, Any]],
    config: dict[str, Any],
    llm_cache_path: Path,
    client: Any | None = None,
    limiter: rate_limits.WindowRateLimiter | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not config.get("llm_cluster_synthesis", True):
        return [
            {
                **cluster,
                "llm_synthesis_status": "disabled",
                "llm_model": str(config.get("llm_model", "")),
                "llm_reasoning_effort": str(config.get("reasoning_effort", "")),
                "llm_prompt_version": LLM_SYNTHESIS_PROMPT_VERSION,
            }
            for cluster in clusters
        ], {"llm_cache_hits": 0, "llm_cache_misses": 0, "llm_failures": 0}
    model = openai_responses.ensure_allowed_synthesis_model(str(config.get("llm_model", openai_responses.DEFAULT_REASONING_MODEL)), field="semantic_clustering.llm_model")
    reasoning_effort = openai_responses.normalize_reasoning_effort(config.get("reasoning_effort", openai_responses.DEFAULT_REASONING_EFFORT))
    max_llm_clusters = int(config.get("max_llm_clusters", 40))
    cache = load_cache(llm_cache_path)
    worker_count = int(config.get("llm_synthesis_workers", 10))
    client = client or (
        FixtureLLMSynthesisClient()
        if os.environ.get("PRODUCT_BASB_LLM_FIXTURE") == "1"
        else OpenAILLMSynthesisClient(
            response_observer=_openai_response_observer(
                limiter,
                stage="semantic_llm_synthesis",
                worker_count=worker_count,
                recommended_knob="llm_synthesis_workers",
            )
        )
    )
    cache_hits = 0
    cache_misses = 0
    failures = 0
    synthesized: list[dict[str, Any] | None] = [None] * len(clusters)
    tasks: list[tuple[int, str, dict[str, Any]]] = []
    for index, cluster in enumerate(clusters):
        if index >= max_llm_clusters:
            synthesized[index] = apply_llm_synthesis(cluster, {}, "skipped-max-clusters", model, reasoning_effort)
            continue
        key = llm_cache_key(cluster, model, reasoning_effort)
        cached = cache["items"].get(key)
        if cached and cached.get("model") == model and cached.get("reasoning_effort") == reasoning_effort:
            cache_hits += 1
            synthesized[index] = apply_llm_synthesis(cluster, cached.get("synthesis", {}), "succeeded", model, reasoning_effort)
            continue
        cache_misses += 1
        tasks.append((index, key, cluster))

    shared_budget = rate_limits.shared_budget_from_config(config, recorder=limiter.recorder if limiter else None)

    def synthesize_task(task: tuple[int, str, dict[str, Any]]) -> tuple[int, str, dict[str, Any], dict[str, Any] | None, Exception | None]:
        index, key, cluster = task
        try:
            token_count = len(json.dumps(compact_cluster_for_llm(cluster), sort_keys=True)) // 4
            if limiter is not None:
                limiter.acquire_openai(
                    stage="semantic_llm_synthesis",
                    worker_count=worker_count,
                    tokens=token_count,
                    recommended_knob="llm_synthesis_workers",
                )
            if shared_budget is not None:
                shared_budget.acquire(
                    stage="semantic_llm_synthesis",
                    worker_count=worker_count,
                    requests=1,
                    tokens=token_count,
                    recommended_knob="llm_synthesis_workers",
                )
            synthesis = client.synthesize_cluster(cluster, model, reasoning_effort)
            return index, key, cluster, synthesis, None
        except Exception as exc:
            return index, key, cluster, None, exc

    if tasks:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="basb-llm-synthesis") as executor:
            results = list(executor.map(synthesize_task, tasks))
        for index, key, cluster, synthesis, error in sorted(results, key=lambda item: item[0]):
            if error is not None or synthesis is None:
                failures += 1
                synthesized[index] = apply_llm_synthesis(cluster, {}, "failed", model, reasoning_effort)
                continue
            cache["items"][key] = {
                "model": model,
                "reasoning_effort": reasoning_effort,
                "prompt_version": LLM_SYNTHESIS_PROMPT_VERSION,
                "card_ids": sorted(str(card_id) for card_id in cluster.get("card_ids", [])),
                "synthesis": synthesis,
            }
            synthesized[index] = apply_llm_synthesis(cluster, synthesis, "succeeded", model, reasoning_effort)
    write_cache(llm_cache_path, cache)
    return [item for item in synthesized if item is not None], {"llm_cache_hits": cache_hits, "llm_cache_misses": cache_misses, "llm_failures": failures}


def cluster_cards(
    cards: list[dict[str, Any]],
    config: dict[str, Any],
    cache_path: Path,
    client: Any | None = None,
    llm_cache_path: Path | None = None,
    llm_client: Any | None = None,
    limiter: rate_limits.WindowRateLimiter | None = None,
    result_cache_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if str(config.get("provider", "openai")).lower() != "openai":
        raise SystemExit("semantic_clustering.provider must be `openai`; local-only semantic clustering is intentionally unsupported.")
    if not cards:
        return {"clusters": [], "stats": {"cache_hits": 0, "cache_misses": 0, "openai_failures": 0, "llm_cache_hits": 0, "llm_cache_misses": 0, "llm_failures": 0}}
    result_cache: dict[str, Any] | None = None
    result_cache_key = semantic_result_cache_key(cards, config)
    if result_cache_path is not None:
        result_cache = load_cache(result_cache_path)
        cached_result = result_cache["items"].get(result_cache_key)
        if not force and isinstance(cached_result, dict) and isinstance(cached_result.get("result"), dict):
            result = dict(cached_result["result"])
            result["stats"] = {
                **(result.get("stats") or {}),
                "result_cache_hits": 1,
                "result_cache_misses": 0,
                "cache_hits": len(cards),
                "cache_misses": 0,
                "llm_cache_hits": len(result.get("clusters", [])),
                "llm_cache_misses": 0,
                "cards_embedded": len(cards),
            }
            return result
    vectors, stats = embed_cards(cards, config, cache_path, client=client, limiter=limiter)
    threshold = float(config["similarity_threshold"])
    min_size = int(config["min_cluster_size"])
    max_clusters = int(config["max_clusters"])
    assigned: set[int] = set()
    clusters: list[dict[str, Any]] = []
    for seed_index, seed in enumerate(cards):
        if seed_index in assigned:
            continue
        members = [seed_index]
        similarities = []
        for index, candidate in enumerate(cards):
            if index == seed_index or index in assigned:
                continue
            score = cosine(vectors[seed_index], vectors[index])
            if score >= threshold:
                members.append(index)
                similarities.append(score)
        if len(members) < min_size:
            continue
        for index in members:
            assigned.add(index)
        member_cards = [cards[index] for index in members]
        clusters.append(
            {
                "id": f"semantic-cluster-{len(clusters) + 1}",
                "theme": theme_for_cards(member_cards),
                "cards": member_cards,
                "card_ids": [card["id"] for card in member_cards],
                "similarity_score": round(sum(similarities) / len(similarities), 4) if similarities else 1.0,
                "evidence_score": min(10, len(member_cards) + len({term for card in member_cards for term in card.get("code_terms", [])})),
                "limitations": [
                    "Cluster membership is based on embedding similarity over compact evidence cards, not full raw-source text.",
                    "Review linked evidence before promoting this packet into delivery work.",
                ],
            }
        )
        if len(clusters) >= max_clusters:
            break
    llm_cache_path = llm_cache_path or cache_path.with_name("llm_cluster_cache.json")
    clusters, llm_stats = synthesize_clusters_with_llm(clusters, config, llm_cache_path, client=llm_client, limiter=limiter)
    stats.update(llm_stats)
    stats.update(
        {
            "semantic_cluster_count": len(clusters),
            "cards_embedded": len(cards),
            "result_cache_hits": 0,
            "result_cache_misses": 1 if result_cache_path is not None else 0,
        }
    )
    result = {"clusters": clusters, "stats": stats}
    if result_cache_path is not None:
        assert result_cache is not None
        result_cache["items"][result_cache_key] = {
            "prompt_version": LLM_SYNTHESIS_PROMPT_VERSION,
            "result": result,
        }
        write_cache(result_cache_path, result_cache)
    return result
