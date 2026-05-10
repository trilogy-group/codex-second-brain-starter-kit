#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Manifest root must be a mapping: {path}")
    return data


def inventory_dir(manifest: dict[str, Any]) -> Path:
    mirror = (manifest.get("sources") or {}).get("mirror_path")
    if not mirror:
        raise SystemExit("Manifest must define sources.mirror_path for benchmark output.")
    return Path(str(mirror)).expanduser() / "inventories"


def vault_path(manifest: dict[str, Any]) -> Path:
    vault = (manifest.get("product") or {}).get("vault_path")
    if not vault:
        raise SystemExit("Manifest must define product.vault_path for benchmark output.")
    return Path(str(vault)).expanduser()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def vault_digest(vault: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(vault.rglob("*.md")):
        if ".obsidian" in path.parts:
            continue
        digest.update(path.relative_to(vault).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_command(command: list[str], *, env: dict[str, str]) -> float:
    started = time.perf_counter()
    subprocess.run(command, check=True, env=env)
    return round(time.perf_counter() - started, 4)


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "---",
        "type: hub",
        "source: generated",
        "tags:",
        "  - benchmark",
        "  - generation-performance",
        "---",
        f"# Benchmark Report - {report['label']}",
        "",
        f"- Manifest: `{report['manifest']}`",
        f"- Runs: `{len(report['runs'])}`",
        f"- Deterministic digest stable: `{'yes' if report.get('digest_stable') else 'no'}`",
        f"- Historical benchmark entries: `{report.get('history', {}).get('entry_count', 0)}`",
        "",
        "## Runs",
        "",
    ]
    for item in report["runs"]:
        cache = item.get("cache_stats", {})
        shards = item.get("shard_summary", {})
        lines.extend(
            [
                f"### Run {item['run']}",
                "",
                f"- Source index seconds: `{item.get('source_index_seconds', 0)}`",
                f"- Rebuild seconds: `{item.get('rebuild_seconds', 0)}`",
                f"- Total seconds: `{item.get('total_seconds', 0)}`",
                f"- Cache hits: `{cache.get('hits', 0)}`",
                f"- Cache misses: `{cache.get('misses', 0)}`",
                f"- Shards merged: `{shards.get('merged_count', 0)}`",
                f"- Shards rejected: `{shards.get('rejected_count', 0)}`",
                f"- Rate-limit wait seconds: `{item.get('rate_limit_wait_seconds', 0)}`",
                f"- Vault digest: `{item.get('vault_digest', '')[:16]}`",
                "",
            ]
        )
    lines.extend(["## Related notes", "", "- [[Intelligence Home]]", "- [[CODE Dashboard]]"])
    return "\n".join(lines).rstrip() + "\n"


def update_history(inventories: Path, report: dict[str, Any]) -> dict[str, Any]:
    history_path = inventories / "benchmark_history.jsonl"
    entry = {
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": report["label"],
        "manifest": report["manifest"],
        "run_count": len(report["runs"]),
        "digest_stable": report.get("digest_stable", False),
        "last_total_seconds": report["runs"][-1].get("total_seconds") if report.get("runs") else None,
        "last_rebuild_seconds": report["runs"][-1].get("rebuild_seconds") if report.get("runs") else None,
        "last_cache_hits": (report["runs"][-1].get("cache_stats") or {}).get("hits", 0) if report.get("runs") else 0,
    }
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    entries: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines()[-50:]:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    durations = [float(item["last_total_seconds"]) for item in entries if isinstance(item.get("last_total_seconds"), (int, float))]
    trends = {
        "schema_version": 1,
        "entry_count": len(entries),
        "latest": entries[-1] if entries else {},
        "average_total_seconds": round(sum(durations) / len(durations), 4) if durations else None,
        "best_total_seconds": min(durations) if durations else None,
        "worst_total_seconds": max(durations) if durations else None,
        "history_path": str(history_path),
    }
    (inventories / "benchmark_trends.json").write_text(json.dumps(trends, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return trends


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark cold and warm Product BASB rebuilds.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--label", default="Product BASB Rebuild")
    parser.add_argument("--skip-source-index", action="store_true")
    parser.add_argument("--fixture-openai", action="store_true")
    args = parser.parse_args()
    if args.runs <= 0:
        raise SystemExit("--runs must be positive.")

    manifest = load_manifest(args.manifest)
    inventories = inventory_dir(manifest)
    vault = vault_path(manifest)
    inventories.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if args.fixture_openai:
        env["PRODUCT_BASB_EMBEDDING_FIXTURE"] = "1"
        env["PRODUCT_BASB_LLM_FIXTURE"] = "1"
        env["PRODUCT_BASB_SHARD_LLM_FIXTURE"] = "1"

    runs: list[dict[str, Any]] = []
    digests: list[str] = []
    for index in range(1, args.runs + 1):
        source_seconds = 0.0
        if not args.skip_source_index or index == 1:
            source_seconds = run_command(
                [sys.executable, str(SCRIPT_DIR / "build_source_indices.py"), "--manifest", str(args.manifest)],
                env=env,
            )
        rebuild_seconds = run_command(
            [sys.executable, str(SCRIPT_DIR / "rebuild_product_brain.py"), "--manifest", str(args.manifest)],
            env=env,
        )
        cache = load_json(inventories / "rebuild_cache.json")
        timings = load_json(inventories / "rebuild_timings.json")
        shards = load_json(inventories / "generation_shards.json")
        rate_events = load_json(inventories / "rate_limit_events.json")
        changed_scope = load_json(inventories / "changed_scope_report.json")
        digest = vault_digest(vault)
        digests.append(digest)
        runs.append(
            {
                "run": index,
                "source_index_seconds": source_seconds,
                "rebuild_seconds": rebuild_seconds,
                "total_seconds": round(source_seconds + rebuild_seconds, 4),
                "cache_stats": cache.get("stats", {}),
                "stage_timings": timings.get("stages", {}),
                "changed_scope": {
                    "changed_counts": changed_scope.get("changed_counts", {}),
                    "impacted_capabilities": changed_scope.get("impacted_capabilities", []),
                    "impacted_code_refs": changed_scope.get("impacted_code_refs", []),
                },
                "shard_summary": shards.get("reducer", {}),
                "rate_limit_summary": rate_events.get("summary", {}),
                "rate_limit_wait_seconds": (rate_events.get("summary") or {}).get("total_wait_seconds", 0),
                "vault_digest": digest,
            }
        )

    report = {
        "schema_version": 1,
        "label": args.label,
        "manifest": str(args.manifest),
        "runs": runs,
        "digest_stable": len(set(digests)) <= 1,
    }
    report["history"] = update_history(inventories, report)
    (inventories / "benchmark_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    benchmark_note = vault / "80 Assets" / "Benchmark Report.md"
    benchmark_note.parent.mkdir(parents=True, exist_ok=True)
    benchmark_note.write_text(render_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
