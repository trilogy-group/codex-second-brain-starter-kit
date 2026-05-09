#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml


VALID_OUTPUT_KINDS = {
    "prd",
    "spec",
    "ticket",
    "pull-request-plan",
    "runbook",
    "decision",
    "launch-note",
    "post-launch-learning",
}


def frontmatter(body: str) -> tuple[dict[str, Any], str]:
    if not body.startswith("---\n"):
        return {}, body
    parts = body.split("---", 2)
    if len(parts) < 3:
        return {}, body
    data = yaml.safe_load(parts[1]) or {}
    return data if isinstance(data, dict) else {}, parts[2].lstrip("\n")


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]+", "", value).strip()
    return cleaned[:140].rstrip(" .") or "Promoted Output"


def wikilink(path: Path) -> str:
    return f"[[{path.stem}]]"


def find_candidate(vault: Path, candidate: str) -> Path:
    raw = Path(candidate).expanduser()
    if raw.exists():
        return raw
    candidates_dir = vault / "30 Initiatives" / "Output Candidates"
    exact = candidates_dir / candidate
    if exact.exists():
        return exact
    if not candidate.endswith(".md"):
        exact = candidates_dir / f"{candidate}.md"
        if exact.exists():
            return exact
    matches = [path for path in candidates_dir.glob("*.md") if path.stem == candidate or path.stem.lower() == candidate.lower()]
    if len(matches) == 1:
        return matches[0]
    raise SystemExit(f"Could not resolve exactly one output candidate for `{candidate}`.")


def render_promoted_note(candidate_path: Path, metadata: dict[str, Any], body: str, *, output_kind: str, decision: str) -> str:
    title = candidate_path.stem.replace("Output Candidate - ", "")
    promoted_frontmatter = {
        **metadata,
        "type": "output",
        "source": "generated",
        "status": "promoted",
        "promotion_status": "promoted",
        "output_kind": output_kind,
        "promoted_from": wikilink(candidate_path),
        "promotion_date": date.today().isoformat(),
    }
    return "\n".join(
        [
            "---",
            yaml.safe_dump(promoted_frontmatter, sort_keys=False).strip(),
            "---",
            f"# {title} {output_kind.replace('-', ' ').title()}",
            "",
            "## Promotion Decision",
            "",
            f"- {decision or 'Promoted from vault-native output candidate.'}",
            "",
            "## Source Candidate",
            "",
            f"- {wikilink(candidate_path)}",
            "",
            "## Draft Body",
            "",
            body.rstrip(),
        ]
    ).rstrip() + "\n"


def update_generated_candidate(candidate_path: Path, metadata: dict[str, Any], body: str, promoted_link: str) -> None:
    if str(metadata.get("source", "")).strip().lower() != "generated":
        return
    metadata = {**metadata, "promotion_status": "promoted", "promoted_output": promoted_link}
    candidate_path.write_text(
        "\n".join(["---", yaml.safe_dump(metadata, sort_keys=False).strip(), "---", body.rstrip(), ""]) ,
        encoding="utf-8",
    )


def promote(vault: Path, candidate: str, *, output_kind: str | None = None, decision: str = "") -> dict[str, Any]:
    candidate_path = find_candidate(vault, candidate)
    metadata, body = frontmatter(candidate_path.read_text(encoding="utf-8"))
    resolved_kind = output_kind or str(metadata.get("output_kind") or "spec")
    if resolved_kind not in VALID_OUTPUT_KINDS:
        raise SystemExit(f"Unsupported output kind `{resolved_kind}`.")
    promoted_dir = vault / "30 Initiatives" / "Promoted Outputs"
    promoted_dir.mkdir(parents=True, exist_ok=True)
    promoted_path = promoted_dir / f"Promoted - {safe_stem(candidate_path.stem.replace('Output Candidate - ', ''))}.md"
    if promoted_path.exists():
        existing_metadata, _existing_body = frontmatter(promoted_path.read_text(encoding="utf-8"))
        if str(existing_metadata.get("source", "")).strip().lower() != "generated":
            raise SystemExit(f"Refusing to overwrite user-authored promoted output: {promoted_path}")
    promoted_path.write_text(
        render_promoted_note(candidate_path, metadata, body, output_kind=resolved_kind, decision=decision),
        encoding="utf-8",
    )
    update_generated_candidate(candidate_path, metadata, body, wikilink(promoted_path))
    return {
        "candidate_path": str(candidate_path),
        "promoted_path": str(promoted_path),
        "promoted_link": wikilink(promoted_path),
        "output_kind": resolved_kind,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote an Obsidian output candidate into the draft output lifecycle.")
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--kind", choices=sorted(VALID_OUTPUT_KINDS))
    parser.add_argument("--decision", default="")
    args = parser.parse_args()
    print(json.dumps(promote(args.vault.expanduser(), args.candidate, output_kind=args.kind, decision=args.decision), indent=2))


if __name__ == "__main__":
    main()
