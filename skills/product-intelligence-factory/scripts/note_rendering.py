#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import incremental_cache

GENERATED_NOTE_MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class NoteRenderSpec:
    path: Path
    cache_namespace: str
    cache_key: str
    payload: Any
    renderer: Callable[[], str]
    generated: bool = False
    cacheable: bool = True
    dependencies: Any | None = None


@dataclass(frozen=True)
class RenderedNote:
    path: Path
    body: str
    generated: bool
    cache_hit: bool
    cache_namespace: str
    cache_key: str


def _render_one(
    spec: NoteRenderSpec,
    cache: dict[str, Any] | None,
    cache_lock: threading.Lock | None,
) -> RenderedNote:
    if cache is None or not spec.cacheable:
        return RenderedNote(
            path=spec.path,
            body=spec.renderer(),
            generated=spec.generated,
            cache_hit=False,
            cache_namespace=spec.cache_namespace,
            cache_key=spec.cache_key,
        )
    assert cache_lock is not None
    with cache_lock:
        cached = incremental_cache.lookup(cache, spec.cache_namespace, spec.cache_key, spec.payload, dependencies=spec.dependencies)
    if cached is not None:
        result = cached
    else:
        body = spec.renderer()
        with cache_lock:
            result = incremental_cache.store(cache, spec.cache_namespace, spec.cache_key, spec.payload, body, dependencies=spec.dependencies)
    return RenderedNote(
        path=spec.path,
        body=str(result.value),
        generated=spec.generated,
        cache_hit=result.hit,
        cache_namespace=spec.cache_namespace,
        cache_key=spec.cache_key,
    )


def render_note_specs(
    specs: list[NoteRenderSpec],
    *,
    cache: dict[str, Any] | None,
    workers: int,
    observed_workers: list[int] | None = None,
) -> list[RenderedNote]:
    if workers <= 0:
        raise SystemExit("note_render_workers must be greater than zero.")
    ordered_specs = sorted(specs, key=lambda item: item.path.as_posix())
    if observed_workers is not None:
        observed_workers.append(workers)
    if not ordered_specs:
        return []
    cache_lock = threading.Lock() if cache is not None else None
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="basb-note-render") as executor:
        rendered = list(executor.map(lambda spec: _render_one(spec, cache, cache_lock), ordered_specs))
    return sorted(rendered, key=lambda item: item.path.as_posix())


def _load_generated_note_manifest(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"schema_version": GENERATED_NOTE_MANIFEST_SCHEMA_VERSION, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid generated notes manifest at {path}; delete it or rerun with --force.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != GENERATED_NOTE_MANIFEST_SCHEMA_VERSION:
        raise SystemExit(
            f"Unsupported generated notes manifest schema at {path}; "
            f"expected schema_version {GENERATED_NOTE_MANIFEST_SCHEMA_VERSION}."
        )
    if not isinstance(payload.get("entries"), dict):
        payload["entries"] = {}
    return payload


def _write_generated_note_manifest(path: Path | None, entries: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": GENERATED_NOTE_MANIFEST_SCHEMA_VERSION,
                "entries": entries,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _path_key(path: Path) -> str:
    return path.expanduser().resolve().as_posix()


def write_rendered_notes(
    rendered_notes: list[RenderedNote],
    *,
    write_note: Callable[[Path, str], None],
    write_generated_note: Callable[[Path, str], None],
    manifest_path: Path | None = None,
) -> dict[str, int]:
    written = 0
    cache_hits = 0
    skipped_unchanged = 0
    deleted_stale = 0
    manifest = _load_generated_note_manifest(manifest_path)
    previous_entries = dict(manifest.get("entries") or {})
    current_entries: dict[str, Any] = {}
    for item in sorted(rendered_notes, key=lambda note: note.path.as_posix()):
        writer = write_generated_note if item.generated else write_note
        body_hash = _body_hash(item.body)
        key = _path_key(item.path)
        current_entries[key] = {
            "path": key,
            "body_sha256": body_hash,
            "generated": item.generated,
            "cache_namespace": item.cache_namespace,
            "cache_key": item.cache_key,
        }
        if item.path.exists() and item.path.read_text(encoding="utf-8", errors="ignore") == item.body:
            skipped_unchanged += 1
        else:
            writer(item.path, item.body)
            written += 1
        if item.cache_hit:
            cache_hits += 1
    for key, entry in previous_entries.items():
        if key in current_entries:
            continue
        stale_path = Path(str(entry.get("path") or key))
        try:
            if stale_path.exists() and stale_path.is_file():
                stale_path.unlink()
                deleted_stale += 1
        except OSError as exc:
            raise SystemExit(f"Unable to delete stale generated note {stale_path}: {exc}") from exc
    _write_generated_note_manifest(manifest_path, current_entries)
    return {
        "written": written,
        "cache_hits": cache_hits,
        "cache_misses": len(rendered_notes) - cache_hits,
        "skipped_unchanged": skipped_unchanged,
        "deleted_stale": deleted_stale,
    }
