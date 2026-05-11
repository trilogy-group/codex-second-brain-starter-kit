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
PLACEHOLDER_TOKEN_RE = re.compile(r"\{\{\s*title\s*\}\}", re.IGNORECASE)
FAILED_GENERATED_SUMMARY_RE = re.compile(r"(unable to summarize file|maybe too big)", re.IGNORECASE)
GENERIC_GENERATED_SUMMARY_TITLE_RE = re.compile(r"(?im)^\s*#?\s*(?:\*\*)?whole file summary(?:\*\*)?\s*$")
RAW_BUSINESS_FIELD_RE = re.compile(
    r"(?im)^(?:[-*]\s*)?(?:target_persona|user_problem|business_value|success_metric|"
    r"evidence_confidence|implementation_leverage|value_score)\s*[:|-]\s*"
    r"(?:\{['\"][^}\n]+['\"]\s*:|\[[\"'][^\]\n]+[\"'](?:\s*,\s*[\"'][^\]\n]+[\"'])*\])"
)
SCAFFOLD_RESIDUE_MARKERS = (
    "Every entity should eventually have an _intelligence_summary.md.",
    "Every summary needs frontmatter and graph connections.",
    "Hub nodes aggregate shared dimensions.",
    "Use timestamped playbooks. Never overwrite prior strategy.",
    "Keep emails, transcripts, and tickets close to the relevant entity.",
)
MARKDOWN_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
EMPTY_JTBD_RE = re.compile(r"(?im)^-\s+\*\*[^*\n]+\*\*:\s*$")
TRACEABILITY_ROW_RE = re.compile(r"^\|(?P<cells>.+)\|$", re.MULTILINE)
OUTPUT_CANDIDATE_LINK_RE = re.compile(r"\[\[Output Candidate - [^\]]+\]\]")

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
    "intermediate-packet": ["type", "area", "status", "date"],
    "output": ["type", "area", "status", "date", "output_kind", "source_packet", "evidence_score", "shipping_path"],
    "archive-record": ["type", "area", "status", "date", "archive_reason"],
    "review": ["type", "area", "status", "date"],
}

BASB_REQUIRED_FIELDS = [
    "basb_stage",
    "para_category",
    "distillation_level",
    "actionability",
]
BASB_NOTE_TYPES = {
    "area",
    "problem",
    "initiative",
    "decision",
    "experiment",
    "metric",
    "insight",
    "capture",
    "review",
    "concept",
    "intermediate-packet",
    "output",
    "archive-record",
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


def collect_notes(vault: Path, ignored: set[Path] | None = None) -> list[Path]:
    ignored = ignored or set()
    return sorted(
        path
        for path in vault.rglob("*.md")
        if ".obsidian" not in path.parts and path.resolve() not in ignored
        and not (
            len(path.parts) >= 2
            and path.parent.name == "80 Assets"
            and path.name.startswith("vault-audit")
        )
    )


def build_resolution_maps(vault: Path, notes: list[Path]) -> tuple[dict[str, list[Path]], dict[str, Path]]:
    by_stem: dict[str, list[Path]] = defaultdict(list)
    by_relative: dict[str, Path] = {}
    for path in notes:
        by_stem[path.stem].append(path)
        relative = path.relative_to(vault).with_suffix("").as_posix()
        by_relative[relative] = path
    return by_stem, by_relative


def markdown_section_body(text: str, heading: str) -> str:
    match = re.search(rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)", text)
    return match.group("body").strip() if match else ""


def product_ontology_residue_markers(path: Path, text: str) -> list[str]:
    if path.stem != "Product Ontology":
        return []
    markers: list[str] = []
    for heading in ("Product purpose", "Jobs to be done", "Business value drivers", "Capabilities"):
        body = markdown_section_body(text, heading)
        if not body:
            markers.append(f"empty Product Ontology section: {heading}")
    if EMPTY_JTBD_RE.search(markdown_section_body(text, "Jobs to be done")):
        markers.append("empty Product Ontology JTBD body")
    return markers


def traceability_residue_markers(path: Path, text: str) -> list[str]:
    if path.stem != "Value Traceability Matrix":
        return []
    markers: list[str] = []
    for match in TRACEABILITY_ROW_RE.finditer(text):
        cells = [cell.strip() for cell in match.group("cells").split("|")]
        if len(cells) < 5 or cells[0] in {"Persona", "---"}:
            continue
        output_cell = cells[-1]
        linked_outputs = OUTPUT_CANDIDATE_LINK_RE.findall(output_cell)
        if len(linked_outputs) > 3:
            markers.append("overbroad traceability output links")
            break
    return markers


def render_report(
    vault: Path,
    total_notes: int,
    type_counts: Counter[str],
    missing_frontmatter: list[Path],
    missing_links: list[Path],
    missing_fields: dict[Path, list[str]],
    missing_basb_fields: dict[Path, list[str]],
    raw_without_distillation: list[Path],
    active_projects_without_review: list[Path],
    orphan_resources: list[Path],
    outputs_without_evidence: list[Path],
    outputs_without_source_packet: list[Path],
    outputs_without_business_value: list[Path],
    packets_without_forward_use: list[Path],
    missing_weekly_reviews: list[str],
    generated_template_residue: dict[Path, list[str]],
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

    if missing_basb_fields:
        lines.extend(["", "## Missing Product BASB Fields"])
        for path, fields in sorted(missing_basb_fields.items(), key=lambda item: str(item[0])):
            field_list = ", ".join(f"`{field}`" for field in fields)
            lines.append(f"- `{path.relative_to(vault)}`: {field_list}")

    if raw_without_distillation:
        lines.extend(["", "## Raw Notes Without Distillation"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in raw_without_distillation)

    if active_projects_without_review:
        lines.extend(["", "## Active Projects Missing Next Review"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in active_projects_without_review)

    if orphan_resources:
        lines.extend(["", "## Orphan Resources"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in orphan_resources)

    if outputs_without_evidence:
        lines.extend(["", "## Outputs Missing Evidence Links"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in outputs_without_evidence)

    if outputs_without_source_packet:
        lines.extend(["", "## Outputs Missing Source Packet"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in outputs_without_source_packet)

    if outputs_without_business_value:
        lines.extend(["", "## Outputs Missing Business Value"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in outputs_without_business_value)

    if packets_without_forward_use:
        lines.extend(["", "## Packets Without Forward Use"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in packets_without_forward_use)

    if missing_weekly_reviews:
        lines.extend(["", "## Missing Weekly Reviews"])
        lines.extend(f"- {item}" for item in missing_weekly_reviews)

    if generated_template_residue:
        lines.extend(["", "## Generated Template Residue"])
        for path, markers in sorted(generated_template_residue.items(), key=lambda item: str(item[0])):
            marker_list = ", ".join(f"`{marker}`" for marker in markers)
            lines.append(f"- `{path.relative_to(vault)}`: {marker_list}")

    if duplicate_stems:
        lines.extend(["", "## Duplicate Stems"])
        for stem, paths in sorted(duplicate_stems.items()):
            joined = ", ".join(f"`{path.relative_to(vault)}`" for path in paths)
            lines.append(f"- `{stem}`: {joined}")

    if orphan_candidates:
        lines.extend(["", "## Orphan Candidates"])
        lines.extend(f"- `{path.relative_to(vault)}`" for path in orphan_candidates)

    if not any(
        [
            missing_frontmatter,
            missing_links,
            missing_fields,
            missing_basb_fields,
            raw_without_distillation,
            active_projects_without_review,
            orphan_resources,
            outputs_without_evidence,
            outputs_without_source_packet,
            outputs_without_business_value,
            packets_without_forward_use,
            missing_weekly_reviews,
            generated_template_residue,
            duplicate_stems,
            orphan_candidates,
        ]
    ):
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

    ignored: set[Path] = set()
    if args.write:
        ignored.add(Path(args.write).expanduser().resolve())

    notes = collect_notes(vault, ignored=ignored)
    by_stem, by_relative = build_resolution_maps(vault, notes)

    inbound: Counter[Path] = Counter()
    outbound: Counter[Path] = Counter()
    type_counts: Counter[str] = Counter()
    missing_frontmatter: list[Path] = []
    missing_links: list[Path] = []
    missing_fields: dict[Path, list[str]] = {}
    missing_basb_fields: dict[Path, list[str]] = {}
    raw_without_distillation: list[Path] = []
    active_projects_without_review: list[Path] = []
    outputs_without_evidence: list[Path] = []
    outputs_without_source_packet: list[Path] = []
    outputs_without_business_value: list[Path] = []
    packets_without_forward_use: list[Path] = []
    weekly_review_notes: list[Path] = []
    generated_template_residue: dict[Path, list[str]] = {}
    frontmatter_by_path: dict[Path, dict[str, object]] = {}

    for path in notes:
        text = path.read_text()
        frontmatter = parse_frontmatter(text)
        frontmatter_by_path[path] = frontmatter
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
        if "90 Templates" not in path.parts and note_type in BASB_NOTE_TYPES:
            missing_basb = [field for field in BASB_REQUIRED_FIELDS if not frontmatter.get(field)]
            if missing_basb:
                missing_basb_fields[path] = missing_basb
        if "90 Templates" not in path.parts and str(frontmatter.get("distillation_level", "")).strip() == "raw":
            if "## Essence" not in text and "## Use in current project" not in text:
                raw_without_distillation.append(path)
        if "90 Templates" not in path.parts and note_type == "initiative":
            status = str(frontmatter.get("status", "")).strip()
            if status in {"active", "proposed"} and not frontmatter.get("next_review"):
                active_projects_without_review.append(path)
        if "90 Templates" not in path.parts and note_type == "output":
            evidence_section = text.split("## Evidence", 1)[1] if "## Evidence" in text else ""
            if "[[" not in evidence_section:
                outputs_without_evidence.append(path)
            if not frontmatter.get("source_packet"):
                outputs_without_source_packet.append(path)
            business_fields = ("target_persona", "user_problem", "business_value", "success_metric", "value_score", "evidence_confidence")
            if any(not frontmatter.get(field) for field in business_fields):
                outputs_without_business_value.append(path)
        if "90 Templates" not in path.parts and note_type == "intermediate-packet":
            forward_targets = ("[[Output Pipeline]]", "[[Initiative", "[[Decision", "[[Weekly Review", "[[Weekly Synthesis")
            if not any(target in text for target in forward_targets):
                packets_without_forward_use.append(path)
        if "90 Templates" not in path.parts and note_type == "review":
            tags = frontmatter.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            if "weekly-review" in tags or path.name.startswith("Weekly Review"):
                weekly_review_notes.append(path)
        if "90 Templates" not in path.parts and str(frontmatter.get("source", "")).strip() == "generated":
            markers: list[str] = []
            if PLACEHOLDER_TOKEN_RE.search(text):
                markers.append("unresolved title placeholder")
            if FAILED_GENERATED_SUMMARY_RE.search(text) or GENERIC_GENERATED_SUMMARY_TITLE_RE.search(text):
                markers.append("failed generated file summary")
            if RAW_BUSINESS_FIELD_RE.search(text):
                markers.append("raw Python-style business field")
            if any(marker in text for marker in SCAFFOLD_RESIDUE_MARKERS):
                markers.append("scaffold operations text")
            markers.extend(product_ontology_residue_markers(path, text))
            markers.extend(traceability_residue_markers(path, text))
            if markers:
                generated_template_residue[path] = markers

    duplicate_stems = {
        stem: paths
        for stem, paths in by_stem.items()
        if len(paths) > 1
    }

    orphan_candidates = [
        path for path in notes
        if inbound[path] == 0 and outbound[path] == 0
    ]
    orphan_resources = [
        path for path in notes
        if "90 Templates" not in path.parts
        and str(frontmatter_by_path.get(path, {}).get("para_category", "")).strip() == "resource"
        and inbound[path] == 0
        and outbound[path] == 0
    ]
    generated_lifecycle_notes = [
        path
        for path, frontmatter in frontmatter_by_path.items()
        if "90 Templates" not in path.parts
        and str(frontmatter.get("source", "")).strip() == "generated"
        and str(frontmatter.get("type", "")).strip() in {"intermediate-packet", "output", "archive-record"}
    ]
    missing_weekly_reviews = []
    if generated_lifecycle_notes and not weekly_review_notes:
        missing_weekly_reviews.append("Generated Product BASB lifecycle notes exist, but no weekly review note was found.")

    report = render_report(
        vault=vault,
        total_notes=len(notes),
        type_counts=type_counts,
        missing_frontmatter=missing_frontmatter,
        missing_links=missing_links,
        missing_fields=missing_fields,
        missing_basb_fields=missing_basb_fields,
        raw_without_distillation=raw_without_distillation,
        active_projects_without_review=active_projects_without_review,
        orphan_resources=orphan_resources,
        outputs_without_evidence=outputs_without_evidence,
        outputs_without_source_packet=outputs_without_source_packet,
        outputs_without_business_value=outputs_without_business_value,
        packets_without_forward_use=packets_without_forward_use,
        missing_weekly_reviews=missing_weekly_reviews,
        generated_template_residue=generated_template_residue,
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
