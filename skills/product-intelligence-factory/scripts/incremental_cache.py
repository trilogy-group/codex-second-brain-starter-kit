#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CacheResult:
    value: Any
    hit: bool
    input_hash: str


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def empty_incremental_cache() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "dependency_graph": {},
        "stats": {
            "hits": 0,
            "misses": 0,
            "skipped_stages": {},
            "invalidations": {},
        },
    }


def load_incremental_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_incremental_cache()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid rebuild cache JSON at {path}; delete the file or rerun the affected stage.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"Unsupported rebuild cache schema at {path}; expected schema_version {SCHEMA_VERSION}.")
    if "entries" not in payload:
        payload["entries"] = {}
    if not isinstance(payload.get("entries"), dict):
        raise SystemExit(f"Invalid rebuild cache entries at {path}; expected a mapping.")
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        payload["stats"] = {"hits": 0, "misses": 0, "skipped_stages": {}}
    payload["stats"].setdefault("hits", 0)
    payload["stats"].setdefault("misses", 0)
    payload["stats"].setdefault("skipped_stages", {})
    payload["stats"].setdefault("invalidations", {})
    if not isinstance(payload.get("dependency_graph"), dict):
        payload["dependency_graph"] = {}
    return payload


def write_incremental_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cache["schema_version"] = SCHEMA_VERSION
    cache.setdefault("entries", {})
    cache.setdefault("dependency_graph", {})
    cache.setdefault("stats", {"hits": 0, "misses": 0, "skipped_stages": {}})
    path.write_text(json.dumps(cache, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def reset_stats(cache: dict[str, Any]) -> None:
    cache["stats"] = {
        "hits": 0,
        "misses": 0,
        "skipped_stages": {},
        "invalidations": {},
    }


def _stage_entries(cache: dict[str, Any], namespace: str) -> dict[str, Any]:
    entries = cache.setdefault("entries", {})
    stage = entries.setdefault(namespace, {})
    if not isinstance(stage, dict):
        raise SystemExit(f"Invalid rebuild cache stage `{namespace}`; expected a mapping.")
    return stage


def _record_hit(cache: dict[str, Any], namespace: str) -> None:
    stats = cache.setdefault("stats", {})
    stats["hits"] = int(stats.get("hits", 0)) + 1
    skipped = stats.setdefault("skipped_stages", {})
    skipped[namespace] = int(skipped.get(namespace, 0)) + 1


def _record_miss(cache: dict[str, Any]) -> None:
    stats = cache.setdefault("stats", {})
    stats["misses"] = int(stats.get("misses", 0)) + 1


def _record_invalidation(cache: dict[str, Any], namespace: str) -> None:
    stats = cache.setdefault("stats", {})
    invalidations = stats.setdefault("invalidations", {})
    invalidations[namespace] = int(invalidations.get(namespace, 0)) + 1


def dependency_hash(dependencies: Any) -> str:
    return stable_hash(dependencies or {})


def _cache_input(input_payload: Any, dependencies: Any | None) -> dict[str, Any]:
    return {
        "input": input_payload,
        "dependencies": dependencies or {},
    }


def _update_dependency_graph(cache: dict[str, Any], namespace: str, key: str, dependencies: Any | None) -> None:
    graph = cache.setdefault("dependency_graph", {})
    graph[f"{namespace}:{key}"] = {
        "namespace": namespace,
        "key": key,
        "dependency_hash": dependency_hash(dependencies),
        "dependencies": dependencies or {},
    }


def get_or_build(
    cache: dict[str, Any],
    namespace: str,
    key: str,
    input_payload: Any,
    builder: Callable[[], Any],
    *,
    dependencies: Any | None = None,
) -> CacheResult:
    input_hash = stable_hash(_cache_input(input_payload, dependencies))
    stage = _stage_entries(cache, namespace)
    entry = stage.get(key)
    if isinstance(entry, dict) and entry.get("input_hash") == input_hash and "value" in entry:
        _record_hit(cache, namespace)
        return CacheResult(value=entry["value"], hit=True, input_hash=input_hash)
    if isinstance(entry, dict):
        _record_invalidation(cache, namespace)
    value = builder()
    stage[key] = {
        "input_hash": input_hash,
        "dependency_hash": dependency_hash(dependencies),
        "dependencies": dependencies or {},
        "value": value,
    }
    _update_dependency_graph(cache, namespace, key, dependencies)
    _record_miss(cache)
    return CacheResult(value=value, hit=False, input_hash=input_hash)


def lookup(cache: dict[str, Any], namespace: str, key: str, input_payload: Any, *, dependencies: Any | None = None) -> CacheResult | None:
    input_hash = stable_hash(_cache_input(input_payload, dependencies))
    stage = _stage_entries(cache, namespace)
    entry = stage.get(key)
    if isinstance(entry, dict) and entry.get("input_hash") == input_hash and "value" in entry:
        _record_hit(cache, namespace)
        _update_dependency_graph(cache, namespace, key, dependencies)
        return CacheResult(value=entry["value"], hit=True, input_hash=input_hash)
    if isinstance(entry, dict):
        _record_invalidation(cache, namespace)
    return None


def store(cache: dict[str, Any], namespace: str, key: str, input_payload: Any, value: Any, *, dependencies: Any | None = None) -> CacheResult:
    input_hash = stable_hash(_cache_input(input_payload, dependencies))
    stage = _stage_entries(cache, namespace)
    stage[key] = {
        "input_hash": input_hash,
        "dependency_hash": dependency_hash(dependencies),
        "dependencies": dependencies or {},
        "value": value,
    }
    _update_dependency_graph(cache, namespace, key, dependencies)
    _record_miss(cache)
    return CacheResult(value=value, hit=False, input_hash=input_hash)
