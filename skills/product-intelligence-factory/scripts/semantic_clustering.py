#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request
from pathlib import Path
from typing import Any


OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"


def default_semantic_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("semantic_clustering") or {})
    return {
        "provider": configured.get("provider", "openai"),
        "embedding_model": configured.get("embedding_model", "text-embedding-3-small"),
        "min_cluster_size": int(configured.get("min_cluster_size", 3)),
        "similarity_threshold": float(configured.get("similarity_threshold", 0.78)),
        "max_clusters": int(configured.get("max_clusters", 40)),
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
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

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
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]


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


def embed_cards(
    cards: list[dict[str, Any]],
    config: dict[str, Any],
    cache_path: Path,
    client: Any | None = None,
) -> tuple[list[list[float]], dict[str, int]]:
    require_openai_or_fixture()
    model = str(config["embedding_model"])
    cache = load_cache(cache_path)
    client = client or (FixtureEmbeddingClient() if os.environ.get("PRODUCT_BASB_EMBEDDING_FIXTURE") == "1" else OpenAIEmbeddingClient())
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
        try:
            embedded = client.embed([text for _, _, text in misses], model)
        except Exception as exc:
            raise SystemExit(f"OpenAI semantic clustering failed before packet synthesis: {exc}") from exc
        for (index, key, text), vector in zip(misses, embedded):
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


def cluster_cards(
    cards: list[dict[str, Any]],
    config: dict[str, Any],
    cache_path: Path,
    client: Any | None = None,
) -> dict[str, Any]:
    if str(config.get("provider", "openai")).lower() != "openai":
        raise SystemExit("semantic_clustering.provider must be `openai`; local-only semantic clustering is intentionally unsupported.")
    if not cards:
        return {"clusters": [], "stats": {"cache_hits": 0, "cache_misses": 0, "openai_failures": 0}}
    vectors, stats = embed_cards(cards, config, cache_path, client=client)
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
    stats.update({"semantic_cluster_count": len(clusters), "cards_embedded": len(cards)})
    return {"clusters": clusters, "stats": stats}
