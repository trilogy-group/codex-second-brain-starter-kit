#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


PROGRESS_SCHEMA_VERSION = 2
UNIT_LABEL = "current refresh work units"
ACTIVE_STATUSES = {"queued", "started", "running"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "canceled"}

DEFAULT_STAGE_PLAN: tuple[tuple[str, str, int], ...] = (
    ("source_index", "Source indexing", 5),
    ("source_extract", "Extracting local sources", 5),
    ("source_fetch", "Fetching linked sources", 5),
    ("rebuild", "Vault rebuild setup", 2),
    ("code_intelligence", "Code intelligence", 12),
    ("load_source_inventories", "Loading source inventories", 4),
    ("source_shards", "Source evidence reducers", 10),
    ("theme_reducers", "Theme reducers", 8),
    ("capability_reducers", "Capability reducers", 8),
    ("ontology_reducer", "Ontology reducer", 4),
    ("generation_shards", "Shard synthesis", 8),
    ("semantic_clustering", "Semantic clustering", 12),
    ("packets_outputs", "Packets and output candidates", 10),
    ("business_value_synthesis", "Business-value synthesis", 18),
    ("note_rendering", "Rendering notes", 30),
    ("generation_shard_reducer", "Reducing shard output", 5),
    ("vault_validation", "Vault validation", 2),
)


def default_planned_stages() -> list[tuple[str, str, int]]:
    return list(DEFAULT_STAGE_PLAN)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stage_label(stage: str) -> str:
    for stage_id, label, _units in DEFAULT_STAGE_PLAN:
        if stage_id == stage:
            return label
    return stage.replace("_", " ").title()


def _positive_int(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _new_stage(stage: str, label: str | None = None, total_units: int = 1) -> dict[str, Any]:
    total = _positive_int(total_units)
    return {
        "stage": stage,
        "label": label or _stage_label(stage),
        "status": "queued",
        "completed_units": 0,
        "total_units": total,
        "missing_units": total,
    }


class ProgressRecorder:
    def __init__(self, inventory_dir: Path, *, reset: bool = False) -> None:
        self.inventory_dir = inventory_dir
        self.snapshot_path = inventory_dir / "generation_progress.json"
        self.event_log_path = inventory_dir / "generation_progress.jsonl"
        self.events: list[dict[str, Any]] = []
        self.stages: dict[str, dict[str, Any]] = {}
        self.max_progress_percent = 0
        self.scope_expanded = False
        self.discovered_total_units = 0
        self.run_id = f"generation-{_now_iso().replace(':', '').replace('-', '')}"
        self.started_at = time.time()
        if reset:
            self._reset_files()
        else:
            self._load_existing_snapshot()

    def _reset_files(self) -> None:
        self.inventory_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.snapshot_path, self.event_log_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _load_existing_snapshot(self) -> None:
        if not self.snapshot_path.exists():
            return
        try:
            snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != PROGRESS_SCHEMA_VERSION:
            return
        self.run_id = str(snapshot.get("run_id") or self.run_id)
        events = snapshot.get("events")
        if isinstance(events, list):
            self.events = [event for event in events if isinstance(event, dict)]
        stages = snapshot.get("stages")
        if isinstance(stages, list):
            for stage in stages:
                if isinstance(stage, dict) and isinstance(stage.get("stage"), str):
                    self.stages[str(stage["stage"])] = {
                        **_new_stage(str(stage["stage"]), str(stage.get("label") or _stage_label(str(stage["stage"])))),
                        **stage,
                    }
        self.max_progress_percent = max(0, min(int(snapshot.get("progress_percent") or 0), 100))
        self.scope_expanded = bool(snapshot.get("scope_expanded", False))
        self.discovered_total_units = _positive_int(snapshot.get("discovered_total_units"), 0)

    def start_run(
        self,
        stage: str = "source_index",
        *,
        planned_stages: list[tuple[str, str, int]] | tuple[tuple[str, str, int], ...] | None = None,
        status: str = "started",
        **details: Any,
    ) -> dict[str, Any]:
        self.stages = {
            stage_id: _new_stage(stage_id, label, units)
            for stage_id, label, units in (planned_stages or DEFAULT_STAGE_PLAN)
        }
        self.max_progress_percent = 0
        self.scope_expanded = False
        self.discovered_total_units = sum(_positive_int(units) for _stage_id, _label, units in (planned_stages or DEFAULT_STAGE_PLAN))
        self.run_id = f"generation-{_now_iso().replace(':', '').replace('-', '')}"
        return self.record(stage, status, **details)

    def has_active_run(self) -> bool:
        if not self.stages:
            return False
        return any(str(stage.get("status") or "queued") not in TERMINAL_STATUSES for stage in self.stages.values())

    def record(self, stage: str, status: str, **details: Any) -> dict[str, Any]:
        self.inventory_dir.mkdir(parents=True, exist_ok=True)
        stage_record = self.stages.setdefault(stage, _new_stage(stage, total_units=details.get("total_units", 1)))
        previous_total_units = _positive_int(stage_record.get("total_units", 1))
        total_units = _positive_int(details.get("total_units", stage_record.get("total_units", 1)))
        if total_units > previous_total_units:
            stage_record["scope_expanded"] = True
            self.scope_expanded = True
        completed_units = details.get("completed_units")
        if completed_units is None and status == "completed":
            completed_units = total_units
        completed = max(0, min(_positive_int(completed_units, stage_record.get("completed_units", 0)), total_units))
        if status in ACTIVE_STATUSES and completed >= total_units:
            completed = max(0, total_units - 1)
        stage_record.update(
            {
                "status": status,
                "completed_units": completed,
                "total_units": total_units,
                "missing_units": max(0, total_units - completed),
            }
        )
        if stage == "rebuild" and status == "completed" and "total_seconds" in details:
            for record in self.stages.values():
                final_total = _positive_int(record.get("total_units"), 1)
                record.update(
                    {
                        "status": "completed",
                        "completed_units": final_total,
                        "missing_units": 0,
                    }
                )
        event = {
            "schema_version": PROGRESS_SCHEMA_VERSION,
            "run_id": self.run_id,
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(time.time() - self.started_at, 4),
            "stage": stage,
            "status": status,
            "details": details,
        }
        self.events.append(event)
        snapshot = self._snapshot(event)
        with self.event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")
        self.snapshot_path.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return event

    def _snapshot(self, event: dict[str, Any]) -> dict[str, Any]:
        stages = [self.stages[key] for key in self.stages]
        total_units = sum(_positive_int(stage.get("total_units")) for stage in stages)
        completed_units = sum(max(0, min(_positive_int(stage.get("completed_units"), 0), _positive_int(stage.get("total_units")))) for stage in stages)
        remaining_units = max(0, total_units - completed_units)
        progress_percent = int(round((completed_units / total_units) * 100)) if total_units else 0
        progress_percent = max(0, min(progress_percent, 100))
        status = str(event.get("status") or "")
        if status in ACTIVE_STATUSES:
            progress_percent = max(progress_percent, self.max_progress_percent)
        if status in ACTIVE_STATUSES and progress_percent >= 100:
            progress_percent = 99
            remaining_units = max(1, remaining_units)
        if status == "completed" and remaining_units == 0:
            progress_percent = 100
            remaining_units = 0
        self.max_progress_percent = max(self.max_progress_percent, progress_percent)
        self.discovered_total_units = max(self.discovered_total_units, total_units)
        current_stage = str(event["stage"])
        current_stage_record = self.stages.get(current_stage, _new_stage(current_stage))
        return {
            "schema_version": PROGRESS_SCHEMA_VERSION,
            "run_id": self.run_id,
            "updated_at": event["observed_at"],
            "current_stage": current_stage,
            "current_stage_label": current_stage_record.get("label") or _stage_label(current_stage),
            "current_status": event["status"],
            "progress_percent": progress_percent,
            "missing_percent": max(0, 100 - progress_percent),
            "completed_units": completed_units,
            "total_units": total_units,
            "remaining_units": remaining_units,
            "discovered_total_units": self.discovered_total_units,
            "scope_expanded": self.scope_expanded or any(bool(stage.get("scope_expanded")) for stage in stages),
            "unit_label": UNIT_LABEL,
            "event_count": len(self.events),
            "stages": stages,
            "events": self.events[-80:],
        }


def load_progress(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": PROGRESS_SCHEMA_VERSION, "load_error": "invalid-json"}
    return data if isinstance(data, dict) else {"schema_version": PROGRESS_SCHEMA_VERSION, "load_error": "invalid-shape"}
