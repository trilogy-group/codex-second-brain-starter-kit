#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CACHEABLE_STATUSES = {
    "auth-gated",
    "binary-or-empty",
    "blocked",
    "likely-auth-gated",
    "local-support-evidence",
    "mirrored",
    "needs-google-drive",
    "stale-doc-reference",
}


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def empty_cache() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "stats": {"hits": 0, "misses": 0, "skipped_sources": 0, "conditional_hits": 0, "invalidations": 0},
    }


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_cache()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid source-index cache JSON at {path}; delete it or rerun source indexing.") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"Unsupported source-index cache schema at {path}; expected schema_version {SCHEMA_VERSION}.")
    data.setdefault("entries", {})
    data.setdefault("stats", {"hits": 0, "misses": 0, "skipped_sources": 0, "conditional_hits": 0, "invalidations": 0})
    return data


def write_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cache["schema_version"] = SCHEMA_VERSION
    cache.setdefault("entries", {})
    cache.setdefault("stats", {})
    path.write_text(json.dumps(cache, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def input_hash(url: str, source_refs: list[str], settings_fingerprint: dict[str, Any]) -> str:
    return stable_hash({"url": url, "source_refs": sorted(source_refs), "settings": settings_fingerprint})


def mirror_still_exists(record: dict[str, Any]) -> bool:
    mirror_path = record.get("mirror_path")
    return not mirror_path or Path(str(mirror_path)).exists()


def lookup(cache: dict[str, Any], url: str, expected_hash: str) -> dict[str, Any] | None:
    entry = cache.get("entries", {}).get(url)
    if not isinstance(entry, dict):
        return None
    record = entry.get("record")
    if entry.get("input_hash") != expected_hash or not isinstance(record, dict):
        cache["stats"]["invalidations"] = int(cache["stats"].get("invalidations", 0)) + 1
        return None
    if record.get("status") not in CACHEABLE_STATUSES or not mirror_still_exists(record):
        cache["stats"]["invalidations"] = int(cache["stats"].get("invalidations", 0)) + 1
        return None
    cache["stats"]["hits"] = int(cache["stats"].get("hits", 0)) + 1
    cache["stats"]["skipped_sources"] = int(cache["stats"].get("skipped_sources", 0)) + 1
    return {**record, "cache_hit": True, "source_index_skipped": True}


def store(cache: dict[str, Any], url: str, hash_value: str, record: dict[str, Any]) -> None:
    if record.get("status") not in CACHEABLE_STATUSES:
        cache["stats"]["misses"] = int(cache["stats"].get("misses", 0)) + 1
        return
    cache.setdefault("entries", {})[url] = {
        "input_hash": hash_value,
        "status": record.get("status"),
        "record": {key: value for key, value in record.items() if key not in {"rate_limit_wait_seconds"}},
    }
    cache["stats"]["misses"] = int(cache["stats"].get("misses", 0)) + 1
