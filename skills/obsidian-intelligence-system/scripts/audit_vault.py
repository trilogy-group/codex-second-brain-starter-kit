#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")

REQUIRED_FIELDS = {
    "intelligence-summary": ["type", "entity", "category", "status", "last_updated"],
    "node": ["type", "node_type", "title"],
    "playbook": ["type", "entity", "date"],
    "area": ["type", "area", "status"],
    "problem": ["type", "area", "status"],
    "initiative": ["type", "area", "status"],
    "decision": ["type", "area", "status"],
    "experiment": ["type", "area", "status"],
    "metric": ["type", "area", "status"],
    "insight": ["type", "area", "status"],
}


def parse_frontmatter(text: str) -> dict[str, object]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    raw = match.group(1)
    if yaml is not None:
        try:
            loaded = yaml.safe_load(raw) or {}
            if isinstance(loaded, dict):
                return loaded
        except yaml.YAMLError:
            pass
    result: dict[str, object] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def normalize_link_target(target: str) -> str:
    target = target.strip()
    target = target.rstrip("/")
    if target.endswith(".md"):
        target = target[:-3]
    return target


def collect_notes(vault: Path) -> list[Path]:
    return sorted(path for path in vault.rglob("*.md") if ".obsidian" not in path.parts)


def build_resolution_maps(vault: Path, notes: list[Path]) -> tuple[dict[str, list[Path]], dict[str, Path]]:
    by_stem: dict[str, list[Path]] = defaultdict(list)
    by_relative: dict[str, Path] = {}
    for path in notes:
        by_stem[path.stem].append(path)
        relative = path.relative_to(vault).with_suffix("").as_posix()
        by_relative[relative] = path
    return by_stem, by_relative


def render_report(
    vault: Path,
    total_notes: int,
    type_counts: Counter[str],
    missing_frontmatter: list[Path],
    missing_links: list[Path],
    missing_fields: dict[Path, list[str]],
    duplicate_stems: dict[str, list[Path]],
    orphan_candidates: list[Path],
) -> str:
    lines = [
        "# Vault Audit",
        "",
        f"- Vault: `{vault}`",
        f"- Total notes: **{total_notes}**",
        "",
        "## Note Types",
    ]
    for note_type, count in sorted(type_counts.items()):
        label = note_type or "(missing type)"
        lines.append(f"- `{label}`: {count}")

    if missing_frontmatter:
        lines.extend(["", "## Missing Frontmatter"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in missing_frontmatter)

    if missing_links:
        lines.extend(["", "## Missing Wikilinks"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in missing_links)

    if missing_fields:
        lines.extend(["", "## Missing Required Fields"])
        for path, fields in sorted(missing_fields.items(), key=lambda item: str(item[0])):
            field_list = ", ".join(f"`{field}`" for field in fields)
            lines.append(f"- `{path.relative_to(vault)}`: {field_list}")

    if duplicate_stems:
        lines.extend(["", "## Duplicate Stems"])
        for stem, paths in sorted(duplicate_stems.items()):
            joined = ", ".join(f"`{path.relative_to(vault)}`" for path in paths)
            lines.append(f"- `{stem}`: {joined}")

    if orphan_candidates:
        lines.extend(["", "## Orphan Candidates"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in orphan_candidates)

    if not any([missing_frontmatter, missing_links, missing_fields, duplicate_stems, orphan_candidates]):
        lines.extend(["", "## Result", "", "No structural issues found by this audit."])

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit an Obsidian vault for structural issues.")
    parser.add_argument("--vault", required=True, help="Absolute path to the vault.")
    parser.add_argument("--write", help="Optional path to write the markdown report.")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.exists():
        print(f"vault not found: {vault}", file=sys.stderr)
        sys.exit(1)

    notes = collect_notes(vault)
    by_stem, by_relative = build_resolution_maps(vault, notes)

    inbound: Counter[Path] = Counter()
    outbound: Counter[Path] = Counter()
    type_counts: Counter[str] = Counter()
    missing_frontmatter: list[Path] = []
    missing_links: list[Path] = []
    missing_fields: dict[Path, list[str]] = {}

    for path in notes:
        text = path.read_text()
        frontmatter = parse_frontmatter(text)
        if not frontmatter:
            missing_frontmatter.append(path)
        note_type = str(frontmatter.get("type", "")).strip()
        type_counts[note_type] += 1

        raw_links = [normalize_link_target(match) for match in WIKILINK_RE.findall(text)]
        if not raw_links:
            missing_links.append(path)
        else:
            outbound[path] = len(raw_links)

        for target in raw_links:
            resolved = None
            if target in by_relative:
                resolved = by_relative[target]
            elif target in by_stem and len(by_stem[target]) == 1:
                resolved = by_stem[target][0]
            if resolved is not None:
                inbound[resolved] += 1

        if "90 Templates" not in path.parts and note_type in REQUIRED_FIELDS:
            missing = [field for field in REQUIRED_FIELDS[note_type] if not frontmatter.get(field)]
            if missing:
                missing_fields[path] = missing

    duplicate_stems = {
        stem: paths
        for stem, paths in by_stem.items()
        if len(paths) > 1
    }

    orphan_candidates = [
        path for path in notes
        if inbound[path] == 0 and outbound[path] == 0
    ]

    report = render_report(
        vault=vault,
        total_notes=len(notes),
        type_counts=type_counts,
        missing_frontmatter=missing_frontmatter,
        missing_links=missing_links,
        missing_fields=missing_fields,
        duplicate_stems=duplicate_stems,
        orphan_candidates=orphan_candidates,
    )

    print(report)

    if args.write:
        output = Path(args.write).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report)


if __name__ == "__main__":
    main()
