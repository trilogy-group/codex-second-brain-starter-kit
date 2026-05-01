#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import textwrap
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)

BASB_DIRS = [
    "00 Home",
    "30 Initiatives/Output Candidates",
    "30 Initiatives/Completed",
    "40 Research/Intermediate Packets",
    "70 Journal/Reviews",
    "80 Assets/Bases",
    "90 Archive/Completed Initiatives",
    "90 Archive/Retired Decisions",
    "90 Archive/Stale Sources",
    "90 Templates",
]

BASB_DEFAULTS = {
    "area": ("organize", "area", "highlighted", "reference"),
    "problem": ("organize", "project", "highlighted", "soon"),
    "initiative": ("organize", "project", "highlighted", "soon"),
    "decision": ("express", "project", "executive", "now"),
    "experiment": ("distill", "project", "highlighted", "soon"),
    "metric": ("organize", "area", "highlighted", "reference"),
    "insight": ("distill", "resource", "distilled", "soon"),
    "capture": ("capture", "resource", "raw", "soon"),
    "review": ("distill", "resource", "executive", "now"),
    "concept": ("distill", "resource", "distilled", "reference"),
    "intermediate-packet": ("distill", "resource", "executive", "soon"),
    "output": ("express", "project", "executive", "now"),
    "archive-record": ("archive", "archive", "executive", "reference"),
}


def parse_frontmatter(text: str) -> dict[str, Any]:
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
    result: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"')
    return result


def is_generated_or_scaffold(path: Path) -> bool:
    source = str(parse_frontmatter(path.read_text(errors="ignore")).get("source", "")).strip()
    return source in {"generated", "scaffold"}


def base_text(type_name: str, title: str, columns: list[str]) -> str:
    properties = "\n".join(f"  {column}:\n    displayName: {column.replace('_', ' ').title()}" for column in columns)
    order = "\n".join(f"      - {column}" for column in columns)
    return textwrap.dedent(
        f"""
        filters: 'type == "{type_name}"'
        properties:
        {properties}
        views:
          - type: table
            name: "{title}"
            order:
        {order}
        """
    ).strip()


def migration_files(product_slug: str) -> dict[str, str]:
    return {
        "00 Home/CODE Dashboard.md": textwrap.dedent(
            f"""
            ---
            type: hub
            area: {product_slug}
            status: active
            source: scaffold
            basb_stage: organize
            para_category: resource
            distillation_level: executive
            actionability: now
            output_target: ""
            tags:
              - basb
              - code
            ---
            # CODE Dashboard

            - Capture: [[00 Journal Hub]]
            - Organize: [[PARA Map]]
            - Distill: [[Intermediate Packet Index]]
            - Express: [[Output Pipeline]]
            - Archive: [[Archive Index]]
            """
        ),
        "00 Home/PARA Map.md": textwrap.dedent(
            f"""
            ---
            type: hub
            area: {product_slug}
            status: active
            source: scaffold
            basb_stage: organize
            para_category: resource
            distillation_level: executive
            actionability: now
            output_target: ""
            tags:
              - basb
              - para
            ---
            # PARA Map

            - Projects: `30 Initiatives/`
            - Areas: `10 Areas/`
            - Resources: `40 Research/`
            - Archives: `90 Archive/`

            Related notes:
            - [[CODE Dashboard]]
            - [[Output Pipeline]]
            - [[Archive Index]]
            """
        ),
        "00 Home/Output Pipeline.md": textwrap.dedent(
            f"""
            ---
            type: hub
            area: {product_slug}
            status: active
            source: scaffold
            basb_stage: express
            para_category: project
            distillation_level: executive
            actionability: now
            output_target: ""
            tags:
              - output
              - express
            ---
            # Output Pipeline

            ![[80 Assets/Bases/Outputs.base#Output Pipeline]]

            Related notes:
            - [[Intermediate Packet Index]]
            - [[Shippable Output Template]]
            """
        ),
        "40 Research/Intermediate Packets/Intermediate Packet Index.md": textwrap.dedent(
            f"""
            ---
            type: hub
            area: {product_slug}
            status: active
            source: scaffold
            basb_stage: distill
            para_category: resource
            distillation_level: executive
            actionability: soon
            output_target: Output Pipeline
            tags:
              - intermediate-packet
            ---
            # Intermediate Packet Index

            ![[80 Assets/Bases/Intermediate Packets.base#Intermediate Packets]]

            Related notes:
            - [[Output Pipeline]]
            - [[CODE Dashboard]]
            """
        ),
        "90 Archive/Archive Index.md": textwrap.dedent(
            f"""
            ---
            type: hub
            area: {product_slug}
            status: active
            source: scaffold
            basb_stage: archive
            para_category: archive
            distillation_level: executive
            actionability: reference
            output_target: ""
            tags:
              - archive
            ---
            # Archive Index

            ![[80 Assets/Bases/Archive Records.base#Archive Records]]

            Related notes:
            - [[Output Pipeline]]
            - [[Intermediate Packet Index]]
            """
        ),
        "90 Templates/Shippable Output Template.md": textwrap.dedent(
            """
            ---
            type: output
            area:
            status: proposed
            date: {{date}}
            basb_stage: express
            para_category: project
            distillation_level: executive
            actionability: now
            output_target:
            output_kind:
            source_packet:
            evidence_score:
            shipping_path:
            tags:
              - output
            ---
            # {{title}}

            ## Decision or ask

            ## Evidence
            - [[Intermediate Packet Index]]

            ## Shipping path
            """
        ),
        "80 Assets/Bases/Intermediate Packets.base": base_text(
            "intermediate-packet",
            "Intermediate Packets",
            ["file.name", "area", "status", "actionability", "output_target"],
        ),
        "80 Assets/Bases/Outputs.base": base_text(
            "output",
            "Output Pipeline",
            ["file.name", "area", "status", "output_kind", "evidence_score", "output_target"],
        ),
        "80 Assets/Bases/Archive Records.base": base_text(
            "archive-record",
            "Archive Records",
            ["file.name", "area", "status", "archive_reason", "date", "output_target"],
        ),
    }


def add_frontmatter_defaults(text: str, product_slug: str) -> tuple[str, list[str], str | None]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return text, [], "missing frontmatter"
    frontmatter = parse_frontmatter(text)
    note_type = str(frontmatter.get("type", "")).strip()
    if note_type not in BASB_DEFAULTS:
        return text, [], f"unsupported note type `{note_type or 'missing'}`"
    stage, para, distillation, actionability = BASB_DEFAULTS[note_type]
    defaults: dict[str, Any] = {
        "area": product_slug if not frontmatter.get("area") else frontmatter.get("area"),
        "basb_stage": stage,
        "para_category": para,
        "distillation_level": distillation,
        "actionability": actionability,
        "output_target": "",
    }
    if note_type == "output":
        defaults.update({"output_kind": "ticket", "source_packet": "", "evidence_score": 0, "shipping_path": ""})
    if note_type == "archive-record":
        defaults["archive_reason"] = "migration-review-needed"
    if note_type == "review":
        defaults["review_period"] = "weekly"
    missing = [key for key, value in defaults.items() if not frontmatter.get(key) and value is not None]
    if not missing:
        return text, [], None
    additions = "\n".join(f"{key}: {defaults[key]}" for key in missing)
    raw = match.group(1).rstrip()
    replacement = f"---\n{raw}\n{additions}\n---\n"
    return replacement + text[match.end():], missing, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate an existing vault toward the Product BASB structure.")
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--product-slug", required=True)
    parser.add_argument("--write", action="store_true", help="Apply changes. The default is dry-run.")
    parser.add_argument("--overwrite-generated", action="store_true", help="Overwrite existing generated or scaffolded BASB files.")
    args = parser.parse_args()

    vault = args.vault.expanduser().resolve()
    if not vault.exists():
        raise SystemExit(f"vault not found: {vault}")

    changed: list[str] = []
    skipped: list[str] = []
    risky: list[str] = []

    for relative in BASB_DIRS:
        path = vault / relative
        if path.exists():
            skipped.append(f"dir exists: `{relative}`")
            continue
        changed.append(f"create dir: `{relative}`")
        if args.write:
            path.mkdir(parents=True, exist_ok=True)

    for relative, content in migration_files(args.product_slug).items():
        path = vault / relative
        if path.exists():
            if args.overwrite_generated and is_generated_or_scaffold(path):
                changed.append(f"overwrite generated file: `{relative}`")
                if args.write:
                    path.write_text(content.strip("\n").rstrip() + "\n")
            else:
                skipped.append(f"file exists: `{relative}`")
            continue
        changed.append(f"create file: `{relative}`")
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content.strip("\n").rstrip() + "\n")

    for path in sorted(vault.rglob("*.md")):
        relative = path.relative_to(vault).as_posix()
        if ".obsidian" in path.parts or "90 Templates" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        new_text, missing, risk = add_frontmatter_defaults(text, args.product_slug)
        if risk:
            risky.append(f"{relative}: {risk}")
            continue
        if not missing:
            skipped.append(f"frontmatter complete: `{relative}`")
            continue
        changed.append(f"patch frontmatter: `{relative}` ({', '.join(missing)})")
        if args.write:
            path.write_text(new_text)

    mode = "write" if args.write else "dry-run"
    lines = [
        "# Product BASB Migration Report",
        "",
        f"- Vault: `{vault}`",
        f"- Product slug: `{args.product_slug}`",
        f"- Mode: `{mode}`",
        f"- Overwrite generated: `{'yes' if args.overwrite_generated else 'no'}`",
        "",
        "## Changed Or Planned",
        "",
    ]
    lines.extend(f"- {item}" for item in changed[:200])
    if len(changed) > 200:
        lines.append(f"- ... `{len(changed) - 200}` more")
    lines.extend(["", "## Skipped", ""])
    lines.extend(f"- {item}" for item in skipped[:120])
    if len(skipped) > 120:
        lines.append(f"- ... `{len(skipped) - 120}` more")
    lines.extend(["", "## Risky Or Manual", ""])
    lines.extend(f"- {item}" for item in risky[:120])
    if len(risky) > 120:
        lines.append(f"- ... `{len(risky) - 120}` more")
    print("\n".join(lines).rstrip() + "\n")


if __name__ == "__main__":
    main()
