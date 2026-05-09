#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rate_limits
import openai_responses


WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
VALID_SHARD_STATUSES = {"queued", "running", "succeeded", "failed", "rejected", "merged"}
SHARD_PROMPT_VERSION = "product-basb-shard-agent-v1"
SHARD_CACHE_SCHEMA_VERSION = 1


def _response_headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", {})
    items = headers.items() if hasattr(headers, "items") else []
    return {str(key): str(value) for key, value in items}


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]+", "", value).strip()
    return cleaned[:120].rstrip(" .") or "Untitled"


def _chunks(items: list[Any], count: int) -> list[list[Any]]:
    if not items or count <= 0:
        return []
    chunk_count = min(count, len(items))
    result = [[] for _ in range(chunk_count)]
    for index, item in enumerate(items):
        result[index % chunk_count].append(item)
    return [chunk for chunk in result if chunk]


def _load_shard_cache(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"schema_version": SHARD_CACHE_SCHEMA_VERSION, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid generation shard cache at {path}; delete it or rerun with --force.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SHARD_CACHE_SCHEMA_VERSION:
        raise SystemExit(f"Unsupported generation shard cache schema at {path}; expected schema_version {SHARD_CACHE_SCHEMA_VERSION}.")
    if not isinstance(payload.get("entries"), dict):
        payload["entries"] = {}
    return payload


def _write_shard_cache(path: Path | None, cache: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    cache["schema_version"] = SHARD_CACHE_SCHEMA_VERSION
    cache.setdefault("entries", {})
    path.write_text(json.dumps(cache, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _shard_cache_key(spec: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "prompt_version": spec.get("prompt_version", SHARD_PROMPT_VERSION),
                "kind": spec.get("kind"),
                "worker_mode": spec.get("worker_mode"),
                "model": spec.get("model"),
                "reasoning_effort": spec.get("reasoning_effort"),
                "cards": spec.get("cards", []),
                "card_ids": spec.get("card_ids", []),
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _string_list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value[:limit] if str(item).strip()]


def _compact_card(kind: str, item: dict[str, Any], index: int) -> dict[str, Any]:
    if kind == "repo-code":
        title = str(item.get("label") or item.get("name") or "Repository")
        return {
            "id": f"repo-code-{index + 1}",
            "kind": kind,
            "title": title,
            "summary": f"Repository source: {title}",
            "capabilities": [],
            "code_reference_links": [],
            "evidence_terms": [],
        }
    signals = item.get("signals") if isinstance(item.get("signals"), dict) else {}
    title = str(
        item.get("stem")
        or item.get("title")
        or item.get("source_ref")
        or signals.get("title")
        or item.get("id")
        or f"Evidence {index + 1}"
    )
    return {
        "id": str(item.get("id") or item.get("source_ref") or item.get("stem") or f"{kind}-{index + 1}"),
        "kind": kind,
        "title": title[:180],
        "summary": str(signals.get("summary") or item.get("summary") or "")[:700],
        "capabilities": _string_list(item.get("capabilities"), 10),
        "code_reference_links": _string_list(item.get("code_reference_links"), 12),
        "evidence_terms": _string_list(signals.get("terms") or item.get("evidence_terms"), 18),
        "quality": item.get("quality") if isinstance(item.get("quality"), dict) else {},
    }


def _item_sort_label(kind: str, item: dict[str, Any]) -> str:
    return str(item.get("stem") or item.get("source_ref") or item.get("id") or item.get("title") or item.get("label") or kind)


def _item_evidence_id(kind: str, item: dict[str, Any]) -> str:
    if kind == "support-evidence":
        return f"support:{item.get('source_ref') or item.get('stem') or ''}"
    if kind == "wiki-evidence":
        return f"wiki:{item.get('source_ref') or item.get('stem') or ''}"
    if kind == "semantic-synthesis":
        return f"semantic:{item.get('id') or item.get('title') or ''}"
    if kind == "repo-code":
        return f"repo:{item.get('label') or ''}"
    return _item_sort_label(kind, item)


def _prioritized_items(kind: str, items: list[dict[str, Any]], changed_scope: dict[str, Any] | None) -> list[dict[str, Any]]:
    changed_ids = set(changed_scope.get("changed_evidence_ids", [])) if isinstance(changed_scope, dict) else set()
    impacted_caps = set(changed_scope.get("impacted_capabilities", [])) if isinstance(changed_scope, dict) else set()
    impacted_code_refs = set(changed_scope.get("impacted_code_refs", [])) if isinstance(changed_scope, dict) else set()

    def priority(item: dict[str, Any]) -> tuple[int, str]:
        score = 0
        if _item_evidence_id(kind, item) in changed_ids:
            score += 100
        capabilities = {str(value) for value in item.get("capabilities", [])}
        score += 20 * len(capabilities.intersection(impacted_caps))
        code_refs = {
            str(value)
            for value in [
                *item.get("code_reference_links", []),
                *(f"{hit.get('repo', '')}/{hit.get('relative_path', '')}" for hit in item.get("code_hits", [])),
            ]
            if str(value).strip()
        }
        score += 10 * len(code_refs.intersection(impacted_code_refs))
        if item.get("conflicts"):
            score += min(8, len(item.get("conflicts", [])))
        quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
        if quality.get("score"):
            score += min(5, int(quality.get("score", 0) or 0))
        return (-score, _item_sort_label(kind, item))

    return sorted(items, key=priority)


def plan_generation_shards(
    *,
    generation_config: dict[str, Any],
    repo_names: list[str],
    support_records: list[dict[str, Any]],
    wiki_records: list[dict[str, Any]],
    semantic_cards: list[dict[str, Any]],
    changed_scope: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    shard_config = generation_config["agent_shards"]
    if not shard_config.get("enabled", True):
        return []
    max_shards = min(12, int(shard_config["max_shards"]))
    max_cards_per_shard = int(shard_config.get("max_cards_per_shard", 80))
    worker_mode = str(shard_config.get("worker_mode", "llm-synthesis"))
    shard_model = openai_responses.ensure_allowed_synthesis_model(
        str(shard_config.get("shard_model", openai_responses.DEFAULT_REASONING_MODEL)),
        field="generation_performance.agent_shards.shard_model",
    )
    reasoning_effort = openai_responses.normalize_reasoning_effort(
        shard_config.get("reasoning_effort", openai_responses.DEFAULT_REASONING_EFFORT)
    )
    source_groups = [
        ("repo-code", _prioritized_items("repo-code", [{"label": name} for name in sorted(repo_names)], changed_scope)),
        ("support-evidence", _prioritized_items("support-evidence", support_records, changed_scope)),
        ("wiki-evidence", _prioritized_items("wiki-evidence", wiki_records, changed_scope)),
        ("semantic-synthesis", _prioritized_items("semantic-synthesis", semantic_cards, changed_scope)),
    ]
    non_empty_groups = [(kind, items) for kind, items in source_groups if items]
    if not non_empty_groups or max_shards <= 0:
        return []

    base_per_group = max(1, max_shards // len(non_empty_groups))
    remaining = max_shards
    specs: list[dict[str, Any]] = []
    for group_index, (kind, items) in enumerate(non_empty_groups):
        groups_left = len(non_empty_groups) - group_index
        target_count = min(len(items), max(1, min(base_per_group, remaining - (groups_left - 1))))
        if group_index == len(non_empty_groups) - 1:
            target_count = min(len(items), remaining)
        for chunk in _chunks(items, target_count):
            if len(specs) >= max_shards:
                break
            labels = [
                str(item.get("stem") or item.get("title") or item.get("id") or item.get("label") or "")[:120]
                for item in chunk[:40]
            ]
            cards = [_compact_card(kind, item, index) for index, item in enumerate(chunk[:max_cards_per_shard])]
            specs.append(
                {
                    "id": f"shard-{len(specs) + 1:02d}",
                    "kind": kind,
                    "status": "queued",
                    "item_count": len(chunk),
                    "labels": labels,
                    "cards": cards,
                    "card_ids": [card["id"] for card in cards],
                    "input_card_count": len(cards),
                    "worker_mode": worker_mode,
                    "model": shard_model,
                    "reasoning_effort": reasoning_effort,
                    "prompt_version": SHARD_PROMPT_VERSION,
                    "writes_final_vault": False,
                }
            )
        remaining = max_shards - len(specs)
        if remaining <= 0:
            break
    return specs


def _frontmatter(body: str) -> dict[str, Any] | None:
    if not body.startswith("---\n"):
        return None
    parts = body.split("---", 2)
    if len(parts) < 3:
        return None
    parsed = yaml.safe_load(parts[1]) or {}
    return parsed if isinstance(parsed, dict) else None


class OpenAIShardClient:
    def __init__(self, api_key: str | None = None, *, response_observer: Callable[[dict[str, str]], None] | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.response_observer = response_observer

    def synthesize_shard(self, spec: dict[str, Any], model: str, reasoning_effort: str = openai_responses.DEFAULT_REASONING_EFFORT) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for LLM generation shards.")
        payload = json.dumps(
            openai_responses.build_json_response_payload(
                model=model,
                reasoning_effort=reasoning_effort,
                instructions=(
                    "You are a Product BASB shard worker. Return compact JSON only with keys "
                    "notes, evidence_cards, and shard_insights. notes must contain title, summary, highlights, "
                    "distilled_takeaways, executive_use, can_feed, and evidence_ids. Do not include raw secrets. "
                    "shard_insights must contain theme, summary, evidence_ids, code_surfaces, and output_rationale."
                ),
                user_content=json.dumps(
                    {
                        "prompt_version": SHARD_PROMPT_VERSION,
                        "shard_id": spec.get("id"),
                        "kind": spec.get("kind"),
                        "cards": spec.get("cards", [])[: int(spec.get("input_card_count", 0) or 0)],
                    },
                    sort_keys=True,
                ),
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
            with urllib.request.urlopen(request, timeout=600) as response:
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


class FixtureShardClient:
    def synthesize_shard(self, spec: dict[str, Any], model: str, reasoning_effort: str = openai_responses.DEFAULT_REASONING_EFFORT) -> dict[str, Any]:
        del model, reasoning_effort
        cards = list(spec.get("cards") or [])
        title = f"{str(spec.get('kind', 'Shard')).replace('-', ' ').title()} Synthesis"
        evidence_ids = [str(card.get("id")) for card in cards[:12] if card.get("id")]
        highlights = [str(card.get("title")) for card in cards[:6] if card.get("title")]
        return {
            "notes": [
                {
                    "title": title,
                    "summary": f"Reusable generated shard synthesis for {spec.get('kind')} evidence.",
                    "highlights": highlights or ["No high-signal evidence cards were available."],
                    "distilled_takeaways": [
                        f"{len(cards)} compact evidence card(s) were available to this shard.",
                        "Review linked source packets before shipping work.",
                    ],
                    "executive_use": "Use this shard as a reducer-validated intermediate work block.",
                    "can_feed": ["Output Pipeline"],
                    "evidence_ids": evidence_ids,
                }
            ],
            "evidence_cards": cards,
            "shard_insights": [
                {
                    "theme": title,
                    "summary": f"Shard-level reusable synthesis for {spec.get('kind')} evidence.",
                    "evidence_ids": evidence_ids,
                    "code_surfaces": _string_list([link for card in cards for link in card.get("code_reference_links", [])], 12),
                    "output_rationale": "Promote if this shard reinforces a packet with code, support, or wiki evidence.",
                    "capabilities": sorted({cap for card in cards for cap in _string_list(card.get("capabilities"), 8)})[:12],
                }
            ],
        }


def _shard_client(*, response_observer: Callable[[dict[str, str]], None] | None = None) -> Any:
    if os.environ.get("PRODUCT_BASB_SHARD_LLM_FIXTURE") == "1" or os.environ.get("PRODUCT_BASB_LLM_FIXTURE") == "1":
        return FixtureShardClient()
    return OpenAIShardClient(response_observer=response_observer)


def _validate_shard_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(payload.get("notes"), list) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    notes = payload.get("notes")
    if isinstance(notes, dict):
        notes = [notes]
    if notes is None and isinstance(payload.get("note"), dict):
        notes = [payload["note"]]
    evidence_cards = payload.get("evidence_cards")
    shard_insights = payload.get("shard_insights")
    if not isinstance(notes, list):
        raise ValueError("Shard LLM response must include a notes list.")
    if not isinstance(evidence_cards, list):
        evidence_cards = []
    if not isinstance(shard_insights, list):
        shard_insights = []
    validated_notes: list[dict[str, Any]] = []
    for note in notes[:3]:
        if not isinstance(note, dict) or not str(note.get("title") or "").strip():
            raise ValueError("Shard LLM note entries must include a title.")
        validated_notes.append(note)
    if not validated_notes:
        raise ValueError("Shard LLM response did not include any usable notes.")
    validated_insights: list[dict[str, Any]] = []
    for insight in shard_insights[:8]:
        if not isinstance(insight, dict):
            continue
        theme = str(insight.get("theme") or "").strip()
        summary = str(insight.get("summary") or "").strip()
        if not theme or not summary:
            continue
        validated_insights.append(
            {
                "theme": theme[:180],
                "summary": summary[:1200],
                "evidence_ids": _string_list(insight.get("evidence_ids"), 40),
                "code_surfaces": _string_list(insight.get("code_surfaces"), 24),
                "output_rationale": str(insight.get("output_rationale") or "").strip()[:1200],
                "capabilities": _string_list(insight.get("capabilities"), 16),
            }
        )
    return validated_notes, [card for card in evidence_cards if isinstance(card, dict)], validated_insights


def _note_lines(value: Any, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value[:limit] if str(item).strip()]


def _write_shard_note(
    *,
    note: dict[str, Any],
    spec: dict[str, Any],
    draft_dir: Path,
    index: int,
) -> str:
    title = _safe_stem(str(note.get("title") or f"Generation Shard {spec['id']}"))
    note_name = _safe_stem(f"Generation Shard - {spec['id']} - {title}") + ".md"
    body = [
        "---",
        "type: shard-record",
        "source: generated",
        "basb_stage: distill",
        "para_category: resource",
        "distillation_level: distilled",
        "actionability: soon",
        f"shard_id: {json.dumps(spec['id'])}",
        f"shard_kind: {json.dumps(spec['kind'])}",
        f"worker_mode: {json.dumps(spec.get('worker_mode', 'llm-synthesis'))}",
        f"llm_model: {json.dumps(spec.get('model', ''))}",
        f"llm_reasoning_effort: {json.dumps(spec.get('reasoning_effort', ''))}",
        f"prompt_version: {json.dumps(SHARD_PROMPT_VERSION)}",
        "---",
        f"# {title}",
        "",
        str(note.get("summary") or "Generated shard synthesis.").strip(),
        "",
        "## Highlights",
    ]
    body.extend(f"- {line}" for line in _note_lines(note.get("highlights")))
    body.extend(["", "## Distilled Takeaways"])
    body.extend(f"- {line}" for line in _note_lines(note.get("distilled_takeaways")))
    body.extend(["", "## Executive Use"])
    executive_use = _note_lines(note.get("executive_use")) or ["Review before use."]
    body.extend(f"- {line}" for line in executive_use)
    body.extend(["", "## Can Feed"])
    can_feed = _note_lines(note.get("can_feed")) or ["Output Pipeline"]
    body.extend(f"- {line}" for line in can_feed)
    body.extend(["", "## Evidence IDs"])
    body.extend(f"- `{line}`" for line in _note_lines(note.get("evidence_ids"), 30))
    body.extend(["", "## Reducer Anchor", "", "- [[Intelligence Home]]"])
    draft_path = draft_dir / note_name
    draft_path.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    return note_name


def llm_shard_worker(
    spec: dict[str, Any],
    scratch_dir: Path,
    *,
    client: Any | None = None,
    limiter: rate_limits.WindowRateLimiter | None = None,
    rate_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    draft_dir = scratch_dir / "draft_notes"
    draft_dir.mkdir(parents=True, exist_ok=True)
    model = openai_responses.ensure_allowed_synthesis_model(
        str(spec.get("model") or openai_responses.DEFAULT_REASONING_MODEL),
        field="generation_performance.agent_shards.shard_model",
    )
    reasoning_effort = openai_responses.normalize_reasoning_effort(
        spec.get("reasoning_effort", openai_responses.DEFAULT_REASONING_EFFORT)
    )
    worker_count = int(spec.get("max_concurrent_shards", 1) or 1)
    rate_config = rate_config or {}
    if client is None and str(spec.get("worker_mode", "")).lower() == "fixture":
        client = FixtureShardClient()
    waited = 0.0
    recorder = limiter.recorder if limiter is not None else rate_limits.RateLimitRecorder()
    if client is None:
        response_observer = None
        if limiter is not None:
            response_observer = lambda headers: limiter.observe_openai_response_headers(
                headers,
                stage="generation_shards",
                worker_count=worker_count,
                recommended_knob="agent_shards.max_concurrent_shards",
            )
        client = _shard_client(response_observer=response_observer)
    if limiter is not None:
        token_count = sum(len(json.dumps(card, sort_keys=True)) for card in spec.get("cards", [])) // 4
        waited += limiter.acquire_openai(
            stage="generation_shards",
            worker_count=worker_count,
            tokens=token_count,
            recommended_knob="agent_shards.max_concurrent_shards",
        )
    else:
        token_count = sum(len(json.dumps(card, sort_keys=True)) for card in spec.get("cards", [])) // 4
    shared_budget = rate_limits.shared_budget_from_config(rate_config or {}, recorder=recorder)
    if shared_budget is not None:
        shared_budget.acquire(
            stage="generation_shards",
            worker_count=worker_count,
            requests=1,
            tokens=token_count,
            recommended_knob="agent_shards.max_concurrent_shards",
        )

    def synthesize() -> dict[str, Any]:
        return client.synthesize_shard(spec, model, reasoning_effort)

    payload, retry_count, retry_wait = rate_limits.with_retries(
        action=synthesize,
        config=rate_config,
        recorder=recorder,
        stage="generation_shards",
        worker_count=worker_count,
        recommended_knob="agent_shards.max_concurrent_shards",
    )
    waited += retry_wait
    notes, evidence_cards, shard_insights = _validate_shard_payload(payload)
    note_names = [
        _write_shard_note(note=note, spec=spec, draft_dir=draft_dir, index=index)
        for index, note in enumerate(notes)
    ]
    (scratch_dir / "evidence_cards.json").write_text(json.dumps(evidence_cards, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (scratch_dir / "shard_insights.json").write_text(json.dumps(shard_insights, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (scratch_dir / "unresolved_links.json").write_text("[]\n", encoding="utf-8")
    result = {
        "id": spec["id"],
        "kind": spec["kind"],
        "status": "succeeded",
        "item_count": spec.get("item_count", 0),
        "worker_mode": spec.get("worker_mode", "llm-synthesis"),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "prompt_version": SHARD_PROMPT_VERSION,
        "input_card_count": len(spec.get("cards", [])),
        "output_note_count": len(note_names),
        "draft_notes": note_names,
        "evidence_card_count": len(evidence_cards),
        "shard_insight_count": len(shard_insights),
        "llm_status": "fixture" if isinstance(client, FixtureShardClient) else "succeeded",
        "retry_count": retry_count,
        "rate_limit_wait_seconds": round(waited, 4),
        "failure": None,
        "seconds": round(time.perf_counter() - started, 4),
    }
    (scratch_dir / "shard_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def default_shard_worker(spec: dict[str, Any], scratch_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    draft_dir = scratch_dir / "draft_notes"
    draft_dir.mkdir(parents=True, exist_ok=True)
    evidence_cards = [
        {
            "id": f"{spec['id']}-{index + 1}",
            "kind": spec["kind"],
            "title": label,
            "source_shard": spec["id"],
        }
        for index, label in enumerate(spec.get("labels", [])[:50])
    ]
    note_name = _safe_stem(f"Generation Shard - {spec['id']} - {spec['kind']}") + ".md"
    note_body = "\n".join(
        [
            "---",
            "type: shard-record",
            "source: generated",
            f"shard_id: {json.dumps(spec['id'])}",
            f"shard_kind: {json.dumps(spec['kind'])}",
            "---",
            f"# Generation Shard - {spec['id']} - {spec['kind']}",
            "",
            f"- Status: `{spec.get('status', 'running')}`",
            f"- Items processed: `{spec.get('item_count', 0)}`",
            "- Reducer target: [[Intelligence Home]]",
        ]
    )
    (draft_dir / note_name).write_text(note_body + "\n", encoding="utf-8")
    (scratch_dir / "evidence_cards.json").write_text(json.dumps(evidence_cards, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (scratch_dir / "shard_insights.json").write_text("[]\n", encoding="utf-8")
    (scratch_dir / "unresolved_links.json").write_text("[]\n", encoding="utf-8")
    result = {
        "id": spec["id"],
        "kind": spec["kind"],
        "status": "succeeded",
        "item_count": spec.get("item_count", 0),
        "draft_notes": [note_name],
        "evidence_card_count": len(evidence_cards),
        "shard_insight_count": 0,
        "failure": None,
        "seconds": round(time.perf_counter() - started, 4),
    }
    (scratch_dir / "shard_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _run_one_shard(
    spec: dict[str, Any],
    scratch_root: Path,
    worker: Callable[[dict[str, Any], Path], dict[str, Any]],
) -> dict[str, Any]:
    scratch_dir = scratch_root / spec["id"]
    scratch_dir.mkdir(parents=True, exist_ok=True)
    running = {**spec, "status": "running", "scratch_dir": str(scratch_dir)}
    started = time.perf_counter()
    try:
        result = worker(running, scratch_dir)
        status = str(result.get("status") or "succeeded")
        if status not in VALID_SHARD_STATUSES:
            status = "succeeded"
        return {
            **running,
            **result,
            "status": status,
            "scratch_dir": str(scratch_dir),
            "seconds": round(time.perf_counter() - started, 4),
        }
    except Exception as exc:  # shard failures are recorded and reduced deterministically.
        failure = {
            **running,
            "status": "failed",
            "failure": str(exc),
            "seconds": round(time.perf_counter() - started, 4),
        }
        (scratch_dir / "shard_result.json").write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return failure


def run_generation_shards(
    *,
    generation_config: dict[str, Any],
    workspace_path: Path,
    repo_names: list[str],
    support_records: list[dict[str, Any]],
    wiki_records: list[dict[str, Any]],
    semantic_cards: list[dict[str, Any]],
    run_id: str | None = None,
    worker: Callable[[dict[str, Any], Path], dict[str, Any]] | None = None,
    rate_limiter: rate_limits.WindowRateLimiter | None = None,
    rate_limit_config: dict[str, Any] | None = None,
    cache_path: Path | None = None,
    force: bool = False,
    changed_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shard_config = generation_config["agent_shards"]
    max_shards = min(12, int(shard_config["max_shards"]))
    max_concurrent = min(6, int(shard_config["max_concurrent_shards"]), max_shards)
    timeout_seconds = int(shard_config.get("timeout_seconds", 1800))
    worker_mode = str(shard_config.get("worker_mode", "llm-synthesis"))
    shard_model = openai_responses.ensure_allowed_synthesis_model(
        str(shard_config.get("shard_model", openai_responses.DEFAULT_REASONING_MODEL)),
        field="generation_performance.agent_shards.shard_model",
    )
    reasoning_effort = openai_responses.normalize_reasoning_effort(
        shard_config.get("reasoning_effort", openai_responses.DEFAULT_REASONING_EFFORT)
    )
    specs = plan_generation_shards(
        generation_config={**generation_config, "agent_shards": {**shard_config, "max_shards": max_shards}},
        repo_names=repo_names,
        support_records=support_records,
        wiki_records=wiki_records,
        semantic_cards=semantic_cards,
        changed_scope=changed_scope,
    )
    run_id = run_id or datetime.now(timezone.utc).strftime("job-%Y%m%dT%H%M%SZ")
    scratch_root = workspace_path / "_generation_shards" / run_id
    scratch_root.mkdir(parents=True, exist_ok=True)
    if worker is None:
        worker = lambda spec, scratch_dir: llm_shard_worker(
            {**spec, "max_concurrent_shards": max_concurrent},
            scratch_dir,
            limiter=rate_limiter,
            rate_config=rate_limit_config,
        )

    if not specs:
        return {
            "enabled": bool(shard_config.get("enabled", True)),
            "run_id": run_id,
            "scratch_root": str(scratch_root),
            "max_shards": max_shards,
            "max_concurrent_shards": max_concurrent,
            "timeout_seconds": timeout_seconds,
            "worker_mode": worker_mode,
            "model": shard_model,
            "reasoning_effort": reasoning_effort,
            "shards": [],
            "cache_hits": 0,
            "cache_misses": 0,
            "status_counts": {},
            "shard_insight_count": 0,
            "shard_insights": [],
            "reducer": {"status": "not-run", "merged_count": 0, "rejected_count": 0},
        }

    shard_cache = _load_shard_cache(cache_path)
    results: list[dict[str, Any]] = []
    specs_to_run: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    for spec in specs[:max_shards]:
        cache_key = _shard_cache_key(spec)
        entry = shard_cache.get("entries", {}).get(cache_key)
        cached_result = entry.get("result") if isinstance(entry, dict) else None
        scratch_dir = Path(str(cached_result.get("scratch_dir", ""))) if isinstance(cached_result, dict) else Path()
        if not force and isinstance(cached_result, dict) and scratch_dir.exists():
            cache_hits += 1
            results.append({**cached_result, "cache_hit": True})
            continue
        cache_misses += 1
        specs_to_run.append({**spec, "cache_key": cache_key})

    with ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="basb-generation-shard") as executor:
        futures = [executor.submit(_run_one_shard, spec, scratch_root, worker) for spec in specs_to_run]
        try:
            for future in as_completed(futures, timeout=timeout_seconds):
                result = future.result()
                result["cache_hit"] = False
                results.append(result)
                cache_key = str(result.get("cache_key") or _shard_cache_key(result))
                shard_cache.setdefault("entries", {})[cache_key] = {
                    "prompt_version": SHARD_PROMPT_VERSION,
                    "result": result,
                }
        except FuturesTimeoutError as exc:
            raise RuntimeError(
                "generation_shards saturated before completion; "
                f"max_concurrent_shards={max_concurrent}, timeout_seconds={timeout_seconds}. "
                "Lower TYLER_SECOND_BRAIN_AGENT_CONCURRENT_SHARDS or raise TYLER_SECOND_BRAIN_AGENT_SHARD_TIMEOUT_SECONDS."
            ) from exc

    _write_shard_cache(cache_path, shard_cache)
    results.sort(key=lambda item: item["id"])
    status_counts = Counter(item["status"] for item in results)
    shard_insights = collect_shard_insights({"shards": results})
    return {
        "enabled": True,
        "run_id": run_id,
        "scratch_root": str(scratch_root),
        "max_shards": max_shards,
        "max_concurrent_shards": max_concurrent,
        "timeout_seconds": timeout_seconds,
        "worker_mode": worker_mode,
        "model": shard_model,
        "reasoning_effort": reasoning_effort,
        "shards": results,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "status_counts": dict(status_counts),
        "shard_insight_count": len(shard_insights),
        "shard_insights": shard_insights,
        "merge_strategy": "deterministic-reducer",
        "reducer": {"status": "pending", "merged_count": 0, "rejected_count": 0},
    }


def _note_title_from_path(path: Path) -> str:
    return path.stem


def _target_for_draft(vault_path: Path, draft_path: Path) -> Path:
    return vault_path / "80 Assets" / "Generation Shards" / draft_path.name


def collect_shard_insights(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    for shard in sorted(inventory.get("shards", []), key=lambda item: item.get("id", "")):
        if shard.get("status") not in {"succeeded", "merged"}:
            continue
        insight_path = Path(str(shard.get("scratch_dir", ""))) / "shard_insights.json"
        if not insight_path.exists():
            continue
        try:
            data = json.loads(insight_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            insights.append(
                {
                    "id": f"{shard.get('id')}-insight-{index + 1}",
                    "source_shard": shard.get("id"),
                    "source_shard_note": f"[[{Path(str((shard.get('draft_notes') or [''])[0])).stem}]]" if shard.get("draft_notes") else "",
                    "shard_kind": shard.get("kind"),
                    "theme": str(item.get("theme") or "").strip(),
                    "summary": str(item.get("summary") or "").strip(),
                    "evidence_ids": _string_list(item.get("evidence_ids"), 40),
                    "code_surfaces": _string_list(item.get("code_surfaces"), 24),
                    "output_rationale": str(item.get("output_rationale") or "").strip(),
                    "capabilities": _string_list(item.get("capabilities"), 16),
                }
            )
    return [item for item in insights if item["theme"] and item["summary"]]


def _is_generated_note(path: Path) -> bool:
    if not path.exists():
        return True
    data = _frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    return bool(data and str(data.get("source", "")).strip().lower() in {"generated", "scaffold"})


def _draft_validation_errors(
    draft_path: Path,
    target_path: Path,
    *,
    duplicate_names: set[str],
    known_note_titles: set[str],
) -> list[str]:
    errors: list[str] = []
    body = draft_path.read_text(encoding="utf-8", errors="ignore")
    data = _frontmatter(body)
    if data is None:
        errors.append("invalid-frontmatter")
    elif str(data.get("source", "")).strip().lower() != "generated":
        errors.append("missing-source-generated")
    if draft_path.name in duplicate_names:
        errors.append("duplicate-note-stem")
    if target_path.exists() and not _is_generated_note(target_path):
        errors.append("user-authored-overwrite")
    unresolved = sorted(
        {
            link.strip()
            for link in WIKILINK_RE.findall(body)
            if link.strip() and link.strip() not in known_note_titles and link.strip() != _note_title_from_path(draft_path)
        }
    )
    if unresolved:
        errors.append("unresolved-wikilinks:" + ",".join(unresolved[:10]))
    return errors


def reduce_generation_shards(
    inventory: dict[str, Any],
    *,
    vault_path: Path,
    known_note_titles: set[str] | None = None,
) -> dict[str, Any]:
    known = set(known_note_titles or set())
    known.update(path.stem for path in vault_path.rglob("*.md") if path.is_file())
    draft_paths_by_shard: dict[str, list[Path]] = {}
    all_draft_names: list[str] = []
    for shard in inventory.get("shards", []):
        if shard.get("status") != "succeeded":
            draft_paths_by_shard[shard["id"]] = []
            continue
        draft_dir = Path(str(shard.get("scratch_dir", ""))) / "draft_notes"
        draft_paths = sorted(draft_dir.glob("*.md")) if draft_dir.exists() else []
        draft_paths_by_shard[shard["id"]] = draft_paths
        all_draft_names.extend(path.name for path in draft_paths)

    duplicates = {name for name, count in Counter(all_draft_names).items() if count > 1}
    merged_count = 0
    rejected_count = 0
    reduced_shards: list[dict[str, Any]] = []
    for shard in sorted(inventory.get("shards", []), key=lambda item: item.get("id", "")):
        shard_id = shard["id"]
        errors: list[str] = []
        planned_writes: list[tuple[Path, Path]] = []
        for draft_path in draft_paths_by_shard.get(shard_id, []):
            target_path = _target_for_draft(vault_path, draft_path)
            draft_errors = _draft_validation_errors(
                draft_path,
                target_path,
                duplicate_names=duplicates,
                known_note_titles=known,
            )
            if draft_errors:
                errors.extend(f"{draft_path.name}:{error}" for error in draft_errors)
            else:
                planned_writes.append((draft_path, target_path))

        if shard.get("status") != "succeeded":
            reduced_shards.append({**shard, "reducer_status": "skipped-failed"})
            continue
        if errors or not planned_writes:
            rejected_count += 1
            reduced_shards.append({**shard, "status": "rejected", "reducer_errors": sorted(errors or ["no-draft-notes"])})
            continue

        for draft_path, target_path in planned_writes:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(draft_path.read_text(encoding="utf-8").rstrip() + "\n", encoding="utf-8")
            known.add(target_path.stem)
        merged_count += 1
        reduced_shards.append(
            {
                **shard,
                "status": "merged",
                "merged_notes": [str(target) for _, target in planned_writes],
            }
        )

    status_counts = Counter(item["status"] for item in reduced_shards)
    shard_insights = collect_shard_insights({**inventory, "shards": reduced_shards})
    return {
        **inventory,
        "shards": reduced_shards,
        "status_counts": dict(status_counts),
        "shard_insight_count": len(shard_insights),
        "shard_insights": shard_insights,
        "reducer": {
            "status": "completed",
            "merged_count": merged_count,
            "rejected_count": rejected_count,
        },
    }
