#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any


SCHEMA_VERSION = 1
SUPPORTED_EVIDENCE_KINDS = {
    "repo-code",
    "repo-doc",
    "uploaded-doc",
    "crawled-url",
    "support-article",
    "wiki-page",
    "docx",
    "pdf",
    "generated-note",
    "reducer-summary",
}
VOLATILE_KEYS = {
    "date",
    "generated_at",
    "run_id",
    "scratch_dir",
    "scratch_root",
    "source_shard",
    "source_shard_note",
    "shard_insight_links",
    "generated_output_candidates",
    "output_candidate_links",
}
VOLATILE_PREFIXES = ("cache_", "timing_", "elapsed_")


def compact_text(value: Any, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    truncated = text[:limit].rsplit(" ", 1)[0].rstrip()
    return f"{truncated}..." if truncated else text[:limit]


def extracted_terms(value: Any, *, limit: int = 12) -> list[str]:
    text = str(value or "")
    terms: list[str] = []
    for phrase in re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,4}\b", text):
        if phrase.casefold() not in {item.casefold() for item in terms}:
            terms.append(phrase)
        if len(terms) >= limit:
            return terms
    for word in re.findall(r"\b[a-z][a-z0-9_-]{4,}\b", text, re.IGNORECASE):
        cleaned = word.strip("._-")
        if len(cleaned) < 5:
            continue
        if cleaned.casefold() not in {item.casefold() for item in terms}:
            terms.append(cleaned)
        if len(terms) >= limit:
            break
    return terms


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    source_kind = str(card.get("source_kind") or card.get("kind") or "generated-note").strip() or "generated-note"
    if source_kind not in SUPPORTED_EVIDENCE_KINDS:
        source_kind = "generated-note"
    title = compact_text(card.get("title") or card.get("source_uri") or card.get("path") or card.get("id") or source_kind, 180)
    summary = compact_text(card.get("summary") or card.get("body") or card.get("text") or title, 900)
    source_uri = str(card.get("source_uri") or card.get("citation_uri") or card.get("path") or card.get("source_ref") or "").strip()
    evidence_id = str(card.get("id") or card.get("evidence_id") or f"{source_kind}:{stable_hash([title, source_uri, summary])[:16]}")
    code_anchors = card.get("code_anchors") or card.get("code_reference_links") or card.get("code_refs") or []
    if not isinstance(code_anchors, list):
        code_anchors = [str(code_anchors)]
    terms = card.get("terms") or card.get("evidence_terms") or extracted_terms(" ".join([title, summary]))
    if not isinstance(terms, list):
        terms = extracted_terms(terms)
    citation = card.get("citation") if isinstance(card.get("citation"), dict) else {}
    return {
        "id": evidence_id,
        "source_kind": source_kind,
        "kind": source_kind,
        "title": title,
        "summary": summary,
        "source_uri": source_uri,
        "path": str(card.get("path") or source_uri),
        "confidence": str(card.get("confidence") or "medium"),
        "terms": [str(item).strip() for item in terms[:18] if str(item).strip()],
        "code_anchors": [str(item).strip() for item in code_anchors[:24] if str(item).strip()],
        "citation": citation,
    }


def cards_from_repo_documents(repo_documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in repo_documents:
        cards.append(
            normalize_card(
                {
                    "id": item.get("id") or f"repo-doc:{item.get('repo', '')}:{item.get('relative_path', '')}",
                    "source_kind": "repo-doc",
                    "title": item.get("title") or item.get("relative_path"),
                    "summary": item.get("summary") or item.get("text") or "",
                    "source_uri": item.get("source_uri") or f"{item.get('repo', '')}/{item.get('relative_path', '')}",
                    "path": item.get("relative_path"),
                    "confidence": item.get("confidence") or "medium",
                    "terms": item.get("terms") or [],
                    "citation": item.get("citation") or {},
                }
            )
        )
    return cards


def cards_from_source_records(records: list[dict[str, Any]], source_kind: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for record in records:
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        signals = record.get("signals") if isinstance(record.get("signals"), dict) else {}
        summary = " ".join(str(value) for value in [*(signals.get("paragraphs") or [])[:2], *(signals.get("bullets") or [])[:3]] if str(value).strip())
        cards.append(
            normalize_card(
                {
                    "id": f"{source_kind}:{record.get('source_ref') or item.get('relative_path') or item.get('source_url') or item.get('title')}",
                    "source_kind": source_kind,
                    "title": signals.get("title") or item.get("title") or record.get("source_ref"),
                    "summary": summary or record.get("text") or "",
                    "source_uri": item.get("source_url") or item.get("relative_path") or record.get("source_ref"),
                    "path": item.get("relative_path") or record.get("source_ref"),
                    "confidence": record.get("confidence") or "medium",
                    "terms": signals.get("terms") or [],
                    "citation": record.get("citation") or {},
                }
            )
        )
    return cards


def cards_from_docx_extracts(docx_extracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in docx_extracts:
        cards.append(
            normalize_card(
                {
                    "id": f"docx:{item.get('relative_path') or item.get('path') or item.get('title')}",
                    "source_kind": "docx",
                    "title": item.get("title") or item.get("relative_path") or item.get("path"),
                    "summary": item.get("summary") or item.get("text") or "",
                    "source_uri": item.get("relative_path") or item.get("path") or "",
                    "confidence": "medium",
                }
            )
        )
    return cards


def cards_from_uploaded_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in documents:
        source_kind = str(item.get("source_kind") or "uploaded-doc")
        cards.append(
            normalize_card(
                {
                    "id": f"{source_kind}:{item.get('relative_path') or item.get('path') or item.get('title')}",
                    "source_kind": source_kind,
                    "title": item.get("title") or item.get("relative_path") or item.get("path"),
                    "summary": item.get("summary") or item.get("text_excerpt") or "",
                    "source_uri": item.get("relative_path") or item.get("path") or "",
                    "confidence": item.get("confidence") or "medium",
                    "terms": item.get("terms") or [],
                }
            )
        )
    return cards


def cards_from_external_links(external_links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in external_links:
        url = item.get("url") or item.get("source_url") or ""
        status = item.get("status") or ""
        if not url:
            continue
        cards.append(
            normalize_card(
                {
                    "id": f"crawled-url:{url}",
                    "source_kind": "crawled-url",
                    "title": item.get("title") or url,
                    "summary": item.get("summary") or f"URL source `{url}` has status `{status}`.",
                    "source_uri": url,
                    "confidence": "low" if status in {"blocked", "auth-gated"} else "medium",
                    "terms": [status] if status else [],
                }
            )
        )
    return cards


def cards_from_code_intelligence(code_intel: dict[str, Any], *, limit: int = 120) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in (code_intel.get("files") or [])[:limit]:
        repo = item.get("repo") or ""
        relative_path = item.get("relative_path") or item.get("path") or ""
        title = f"{repo}/{relative_path}".strip("/")
        summary = " ".join(
            str(value)
            for value in [
                item.get("artifact_kind"),
                item.get("language"),
                f"routes={item.get('route_count', 0)}",
                f"schemas={item.get('schema_count', 0)}",
                f"tests={item.get('test_anchor_count', 0)}",
            ]
            if str(value).strip()
        )
        cards.append(
            normalize_card(
                {
                    "id": f"repo-code:{title}",
                    "source_kind": "repo-code",
                    "title": title,
                    "summary": summary,
                    "source_uri": title,
                    "confidence": "medium",
                    "terms": [*(item.get("symbols") or {}).get("functions", [])[:8], *(item.get("symbols") or {}).get("classes", [])[:8]],
                    "code_anchors": [title] if title else [],
                }
            )
        )
    return cards


def source_kind_counts(cards: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(card.get("source_kind") or card.get("kind") or "generated-note") for card in cards))


def stable_cards(
    cards: list[dict[str, Any]],
    *,
    limit: int | None = None,
    include_generated_notes: bool = True,
) -> list[dict[str, Any]]:
    normalized = [normalize_card(card) for card in cards]
    compact = [
        {
            "id": card["id"],
            "source_kind": card["source_kind"],
            "title": card["title"],
            "summary": card["summary"],
            "source_uri": card["source_uri"],
            "confidence": card["confidence"],
            "terms": sorted(set(card["terms"])),
            "code_anchors": sorted(set(card["code_anchors"])),
        }
        for card in normalized
        if include_generated_notes or card["source_kind"] != "generated-note"
    ]
    compact.sort(key=lambda item: (item["source_kind"], item["id"], item["title"]))
    return compact[:limit] if limit is not None else compact


def stable_business_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return sorted((stable_business_payload(item) for item in payload), key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(payload, dict):
        if "evidence_cards" in payload and isinstance(payload["evidence_cards"], list):
            payload = {
                **payload,
                "evidence_cards": stable_cards(
                    payload["evidence_cards"],
                    include_generated_notes=bool(payload.get("generated_notes_feed_synthesis", False)),
                ),
            }
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            if key_text in VOLATILE_KEYS or any(key_text.startswith(prefix) for prefix in VOLATILE_PREFIXES):
                continue
            cleaned[key_text] = stable_business_payload(value)
        return cleaned
    return payload
