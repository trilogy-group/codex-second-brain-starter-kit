#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_INDEX_SCHEMA_VERSION = 1
DEFAULT_RETRIEVAL_INDEX: dict[str, Any] = {
    "enabled": True,
    "max_candidates_per_source": 30,
    "min_score": 0.0,
}

RETRIEVAL_ENV_OVERRIDES = {
    "enabled": ("PRODUCT_BASB_RETRIEVAL_INDEX_ENABLED", "TYLER_SECOND_BRAIN_RETRIEVAL_INDEX_ENABLED"),
    "max_candidates_per_source": (
        "PRODUCT_BASB_RETRIEVAL_MAX_CANDIDATES_PER_SOURCE",
        "TYLER_SECOND_BRAIN_RETRIEVAL_MAX_CANDIDATES_PER_SOURCE",
    ),
    "min_score": ("PRODUCT_BASB_RETRIEVAL_MIN_SCORE", "TYLER_SECOND_BRAIN_RETRIEVAL_MIN_SCORE"),
}


@dataclass(frozen=True)
class EvidenceRow:
    evidence_id: str
    kind: str
    title: str
    body: str
    source_ref: str
    path: str
    capabilities: list[str] = field(default_factory=list)
    code_refs: list[str] = field(default_factory=list)
    fingerprint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EvidenceRow":
        capabilities = sorted({str(item) for item in self.capabilities if str(item).strip()})
        code_refs = sorted({str(item) for item in self.code_refs if str(item).strip()})
        metadata = json.loads(json.dumps(self.metadata, sort_keys=True, default=str))
        fingerprint = self.fingerprint or row_content_hash(
            {
                "evidence_id": self.evidence_id,
                "kind": self.kind,
                "title": self.title,
                "body": self.body,
                "source_ref": self.source_ref,
                "path": self.path,
                "capabilities": capabilities,
                "code_refs": code_refs,
                "metadata": metadata,
            }
        )
        return EvidenceRow(
            evidence_id=str(self.evidence_id),
            kind=str(self.kind),
            title=str(self.title),
            body=str(self.body),
            source_ref=str(self.source_ref),
            path=str(self.path),
            capabilities=capabilities,
            code_refs=code_refs,
            fingerprint=fingerprint,
            metadata=metadata,
        )

    def to_record(self) -> dict[str, Any]:
        row = self.normalized()
        return {
            "evidence_id": row.evidence_id,
            "kind": row.kind,
            "title": row.title,
            "body": row.body,
            "source_ref": row.source_ref,
            "path": row.path,
            "capabilities": row.capabilities,
            "code_refs": row.code_refs,
            "fingerprint": row.fingerprint,
            "metadata": row.metadata,
        }


def row_content_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _configured_value(configured: dict[str, Any], field: str, default: Any) -> Any:
    for env_name in RETRIEVAL_ENV_OVERRIDES.get(field, ()):
        value = os.environ.get(env_name)
        if value not in (None, ""):
            return value
    return configured.get(field, default)


def _configured_bool(configured: dict[str, Any], field: str, default: bool) -> bool:
    value = _configured_value(configured, field, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _non_negative_float(value: Any, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"retrieval_index.{field} must be a non-negative number.") from exc
    if parsed < 0:
        raise SystemExit(f"retrieval_index.{field} must be zero or greater.")
    return parsed


def _positive_int(value: Any, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"retrieval_index.{field} must be a positive integer.") from exc
    if parsed <= 0:
        raise SystemExit(f"retrieval_index.{field} must be greater than zero.")
    return parsed


def default_retrieval_config(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = dict((profile or {}).get("retrieval_index") or {})
    return {
        "enabled": _configured_bool(configured, "enabled", DEFAULT_RETRIEVAL_INDEX["enabled"]),
        "max_candidates_per_source": _positive_int(
            _configured_value(configured, "max_candidates_per_source", DEFAULT_RETRIEVAL_INDEX["max_candidates_per_source"]),
            field="max_candidates_per_source",
        ),
        "min_score": _non_negative_float(
            _configured_value(configured, "min_score", DEFAULT_RETRIEVAL_INDEX["min_score"]),
            field="min_score",
        ),
    }


def sqlite_fts_available() -> bool:
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE evidence_fts_test USING fts5(title, body)")
        connection.close()
        return True
    except sqlite3.Error:
        return False


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence (
          evidence_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          source_ref TEXT NOT NULL,
          path TEXT NOT NULL,
          capabilities_json TEXT NOT NULL,
          code_refs_json TEXT NOT NULL,
          fingerprint TEXT NOT NULL,
          metadata_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_evidence_kind ON evidence(kind)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_evidence_fingerprint ON evidence(fingerprint)")
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
          evidence_id UNINDEXED,
          kind,
          title,
          body,
          source_ref,
          path,
          capabilities,
          code_refs
        )
        """
    )


def _row_from_sql(row: sqlite3.Row) -> EvidenceRow:
    return EvidenceRow(
        evidence_id=str(row["evidence_id"]),
        kind=str(row["kind"]),
        title=str(row["title"]),
        body=str(row["body"]),
        source_ref=str(row["source_ref"]),
        path=str(row["path"]),
        capabilities=[str(item) for item in json.loads(row["capabilities_json"] or "[]")],
        code_refs=[str(item) for item in json.loads(row["code_refs_json"] or "[]")],
        fingerprint=str(row["fingerprint"]),
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def load_rows(index_path: Path) -> list[EvidenceRow]:
    if not index_path.exists():
        return []
    with _connect(index_path) as connection:
        ensure_schema(connection)
        rows = [_row_from_sql(row) for row in connection.execute("SELECT * FROM evidence ORDER BY evidence_id")]
    return rows


def _prepare_rows(rows: Iterable[EvidenceRow]) -> list[EvidenceRow]:
    deduped: dict[str, EvidenceRow] = {}
    for row in rows:
        normalized = row.normalized()
        if not normalized.evidence_id.strip():
            continue
        deduped[normalized.evidence_id] = normalized
    return [deduped[key] for key in sorted(deduped)]


def rebuild_index(
    index_path: Path,
    rows: Iterable[EvidenceRow],
    *,
    manifest_path: Path | None = None,
    delete_stale: bool = True,
) -> dict[str, Any]:
    prepared = _prepare_rows(rows)
    if not sqlite_fts_available():
        raise SystemExit("SQLite FTS5 is required for retrieval_index; disable retrieval_index.enabled or use a Python sqlite3 build with FTS5.")
    previous_ids: set[str] = set()
    now = datetime.now(timezone.utc).isoformat()
    with _connect(index_path) as connection:
        ensure_schema(connection)
        previous_ids = {str(row["evidence_id"]) for row in connection.execute("SELECT evidence_id FROM evidence")}
        current_ids = {row.evidence_id for row in prepared}
        stale_ids = sorted(previous_ids - current_ids) if delete_stale else []
        with connection:
            for evidence_id in stale_ids:
                connection.execute("DELETE FROM evidence WHERE evidence_id = ?", (evidence_id,))
                connection.execute("DELETE FROM evidence_fts WHERE evidence_id = ?", (evidence_id,))
            for row in prepared:
                record = row.to_record()
                connection.execute("DELETE FROM evidence_fts WHERE evidence_id = ?", (record["evidence_id"],))
                connection.execute(
                    """
                    INSERT INTO evidence (
                      evidence_id, kind, title, body, source_ref, path, capabilities_json,
                      code_refs_json, fingerprint, metadata_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(evidence_id) DO UPDATE SET
                      kind=excluded.kind,
                      title=excluded.title,
                      body=excluded.body,
                      source_ref=excluded.source_ref,
                      path=excluded.path,
                      capabilities_json=excluded.capabilities_json,
                      code_refs_json=excluded.code_refs_json,
                      fingerprint=excluded.fingerprint,
                      metadata_json=excluded.metadata_json,
                      updated_at=excluded.updated_at
                    """,
                    (
                        record["evidence_id"],
                        record["kind"],
                        record["title"],
                        record["body"],
                        record["source_ref"],
                        record["path"],
                        json.dumps(record["capabilities"], sort_keys=True),
                        json.dumps(record["code_refs"], sort_keys=True),
                        record["fingerprint"],
                        json.dumps(record["metadata"], sort_keys=True, default=str),
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO evidence_fts (evidence_id, kind, title, body, source_ref, path, capabilities, code_refs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["evidence_id"],
                        record["kind"],
                        record["title"],
                        record["body"],
                        record["source_ref"],
                        record["path"],
                        " ".join(record["capabilities"]),
                        " ".join(record["code_refs"]),
                    ),
                )
    stats = {
        "enabled": True,
        "schema_version": EVIDENCE_INDEX_SCHEMA_VERSION,
        "fts_available": True,
        "indexed_rows": len(prepared),
        "deleted_rows": len(stale_ids),
        "index_path": str(index_path),
    }
    if manifest_path is not None:
        write_manifest(manifest_path, prepared, stats)
    return stats


def write_manifest(path: Path, rows: list[EvidenceRow], stats: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": EVIDENCE_INDEX_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "fingerprint": row_content_hash([row.to_record() for row in rows]),
        "kind_counts": {
            kind: sum(1 for row in rows if row.kind == kind)
            for kind in sorted({row.kind for row in rows})
        },
        "stats": stats,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fts_query(value: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]{3,}", value.lower())
    tokens = [token for index, token in enumerate(tokens) if token not in tokens[:index]]
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens[:32])


def _query_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_]{3,}", value.lower())
    return [token for index, token in enumerate(tokens) if token not in tokens[:index]][:32]


def search(
    index_path: Path,
    query: str,
    *,
    limit: int = 30,
    kinds: list[str] | None = None,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    if limit <= 0 or not index_path.exists():
        return []
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    where = ["evidence_fts MATCH ?"]
    params: list[Any] = [fts_query]
    if kinds:
        placeholders = ", ".join("?" for _ in kinds)
        where.append(f"e.kind IN ({placeholders})")
        params.extend(kinds)
    sql_limit = max(limit * 4, limit)
    params.append(sql_limit)
    sql = f"""
        SELECT
          e.*,
          bm25(evidence_fts, 0.2, 0.4, 2.0, 1.0, 0.2, 0.2, 0.1) AS bm25_score
        FROM evidence_fts
        JOIN evidence e ON e.evidence_id = evidence_fts.evidence_id
        WHERE {' AND '.join(where)}
        ORDER BY bm25_score ASC, e.kind ASC, e.path ASC, e.evidence_id ASC
        LIMIT ?
    """
    with _connect(index_path) as connection:
        ensure_schema(connection)
        rows = list(connection.execute(sql, params))
    results: list[dict[str, Any]] = []
    query_tokens = _query_tokens(query)
    for row in rows:
        score = round(-float(row["bm25_score"]), 8)
        if score < min_score:
            continue
        evidence = _row_from_sql(row).to_record()
        haystack = f"{evidence['title']} {evidence['body']} {evidence['source_ref']} {evidence['path']}".lower()
        exact_matches = sum(1 for token in query_tokens if re.search(rf"\b{re.escape(token)}\b", haystack))
        evidence["score"] = score
        evidence["exact_match_count"] = exact_matches
        results.append(evidence)
    results.sort(key=lambda item: (-int(item.get("exact_match_count", 0)), -float(item.get("score", 0.0)), item["kind"], item["path"], item["evidence_id"]))
    return results[:limit]


def changed_scope_report(
    previous_rows: Iterable[EvidenceRow],
    current_rows: Iterable[EvidenceRow],
    *,
    force: bool = False,
) -> dict[str, Any]:
    previous = {row.evidence_id: row.normalized() for row in previous_rows}
    current = {row.evidence_id: row.normalized() for row in current_rows}
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    unchanged: list[str] = []
    if force:
        modified = sorted(current)
        deleted = sorted(set(previous) - set(current))
    else:
        added = sorted(set(current) - set(previous))
        deleted = sorted(set(previous) - set(current))
        for evidence_id in sorted(set(current).intersection(previous)):
            if current[evidence_id].fingerprint == previous[evidence_id].fingerprint:
                unchanged.append(evidence_id)
            else:
                modified.append(evidence_id)

    changed_ids = sorted(set(added + modified + deleted))
    impacted_rows = [current[evidence_id] for evidence_id in added + modified if evidence_id in current]
    impacted_rows.extend(previous[evidence_id] for evidence_id in deleted if evidence_id in previous)
    impacted_capabilities = sorted({capability for row in impacted_rows for capability in row.capabilities})
    impacted_code_refs = sorted({code_ref for row in impacted_rows for code_ref in row.code_refs})
    impacted_kinds = {
        kind: sum(1 for row in impacted_rows if row.kind == kind)
        for kind in sorted({row.kind for row in impacted_rows})
    }
    return {
        "schema_version": EVIDENCE_INDEX_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "force": force,
        "changed_scope_rebuild": True,
        "changed_counts": {
            "added": len(added),
            "modified": len(modified),
            "deleted": len(deleted),
            "unchanged": len(unchanged),
            "total_current": len(current),
            "total_previous": len(previous),
        },
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "changed_evidence_ids": changed_ids,
        "impacted_capabilities": impacted_capabilities,
        "impacted_code_refs": impacted_code_refs,
        "impacted_kinds": impacted_kinds,
    }


def write_changed_scope_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
