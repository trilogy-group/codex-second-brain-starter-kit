#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path


CORE_PLUGINS = {
    "file-explorer": True,
    "global-search": True,
    "switcher": True,
    "graph": True,
    "backlink": True,
    "canvas": True,
    "outgoing-link": True,
    "tag-pane": True,
    "footnotes": False,
    "properties": True,
    "page-preview": True,
    "daily-notes": True,
    "templates": True,
    "note-composer": True,
    "command-palette": True,
    "slash-command": False,
    "editor-status": True,
    "bookmarks": True,
    "markdown-importer": False,
    "zk-prefixer": False,
    "random-note": False,
    "outline": True,
    "word-count": True,
    "slides": False,
    "audio-recorder": False,
    "workspaces": True,
    "file-recovery": True,
    "publish": False,
    "sync": False,
    "bases": True,
    "webviewer": False,
}


def title_case(text: str) -> str:
    words = text.replace("-", " ").replace("_", " ").split()
    return " ".join(word.capitalize() for word in words) or text


def write_file(path: Path, content: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        print(f"skip {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip("\n").rstrip() + "\n")
    print(f"wrote {path}")


def json_text(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=False)


def display_name(column: str) -> str:
    if column == "file.name":
        return "Name"
    return title_case(column.replace(".", " "))


def base_text(type_name: str, title: str, columns: list[str]) -> str:
    properties = "\n".join(
        [f"  {column}:\n    displayName: {display_name(column)}" for column in columns]
    )
    order = "\n".join([f"      - {column}" for column in columns])
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


def inbox_base_text() -> str:
    return textwrap.dedent(
        """
        filters: file.hasTag("inbox")
        properties:
          file.name:
            displayName: Name
          type:
            displayName: Type
          status:
            displayName: Status
        views:
          - type: table
            name: "Inbox"
            order:
              - file.name
              - type
              - status
        """
    ).strip()


def intelligence_canvas(mode: str) -> str:
    nodes = [
        {
            "id": "home",
            "type": "file",
            "file": "00 Home/Intelligence Home.md",
            "x": 0,
            "y": 0,
            "width": 420,
            "height": 260,
        },
        {
            "id": "journal",
            "type": "file",
            "file": "70 Journal/00 Journal Hub.md",
            "x": 520,
            "y": 220,
            "width": 360,
            "height": 220,
        },
    ]
    edges = [
        {
            "id": "home-journal",
            "fromNode": "home",
            "toNode": "journal",
            "fromSide": "right",
            "toSide": "left",
        }
    ]

    if mode in {"product", "hybrid"}:
        nodes.extend(
            [
                {
                    "id": "product",
                    "type": "file",
                    "file": "00 Home/Product OS.md",
                    "x": 520,
                    "y": -120,
                    "width": 360,
                    "height": 240,
                },
                {
                    "id": "research",
                    "type": "file",
                    "file": "40 Research/00 Research Hub.md",
                    "x": -520,
                    "y": -120,
                    "width": 360,
                    "height": 240,
                },
            ]
        )
        edges.extend(
            [
                {
                    "id": "home-product",
                    "fromNode": "home",
                    "toNode": "product",
                    "fromSide": "right",
                    "toSide": "left",
                },
                {
                    "id": "home-research",
                    "fromNode": "home",
                    "toNode": "research",
                    "fromSide": "left",
                    "toSide": "right",
                },
            ]
        )

    if mode in {"operations", "hybrid"}:
        nodes.append(
            {
                "id": "operations",
                "type": "file",
                "file": "Operations/INDEX.md",
                "x": -520,
                "y": 220,
                "width": 360,
                "height": 220,
            }
        )
        edges.append(
            {
                "id": "home-operations",
                "fromNode": "home",
                "toNode": "operations",
                "fromSide": "left",
                "toSide": "right",
            }
        )

    return json.dumps({"nodes": nodes, "edges": edges}, indent=2)


def home_links(mode: str) -> list[str]:
    links = ["[[00 Journal Hub]]", "[[TRAVERSAL-INDEX]]", "[[Intelligence Map.canvas]]"]
    if mode in {"product", "hybrid"}:
        links.extend(["[[Product OS]]", "[[00 Research Hub]]"])
    if mode in {"operations", "hybrid"}:
        links.append("[[Operations/INDEX]]")
    return links


def scaffold_common(vault: Path, project: str, mode: str, overwrite: bool) -> None:
    common_dirs = [
        vault / ".obsidian",
        vault / "00 Home",
        vault / "70 Journal" / "Daily",
        vault / "80 Assets" / "Bases",
        vault / "80 Assets" / "Canvas",
        vault / "90 Templates",
    ]
    for directory in common_dirs:
        directory.mkdir(parents=True, exist_ok=True)

    write_file(vault / ".obsidian" / "core-plugins.json", json_text(CORE_PLUGINS), overwrite)
    write_file(vault / ".obsidian" / "templates.json", json_text({"folder": "90 Templates"}), overwrite)
    write_file(
        vault / ".obsidian" / "daily-notes.json",
        json_text(
            {
                "folder": "70 Journal/Daily",
                "template": "90 Templates/Daily Note",
                "format": "YYYY-MM-DD ddd",
            }
        ),
        overwrite,
    )

    home_lines = [
        "---",
        "type: hub",
        f'area: "{project}"',
        "status: active",
        "source: scaffold",
        "confidence: high",
        "tags:",
        "  - intelligence-home",
        "---",
        "# Intelligence Home",
        "",
        f"This is the root note for the {project} intelligence system.",
        "",
        "Start here:",
    ]
    home_lines.extend(f"- {link}" for link in home_links(mode))
    write_file(vault / "00 Home" / "Intelligence Home.md", "\n".join(home_lines), overwrite)

    write_file(
        vault / "70 Journal" / "00 Journal Hub.md",
        textwrap.dedent(
            """
            ---
            type: hub
            area: journal
            status: active
            source: scaffold
            confidence: high
            tags:
              - journal
            ---
            # 00 Journal Hub

            Use daily notes as the capture inbox. Turn raw material into durable notes weekly.

            Templates:
            - [[Daily Note]]
            - [[Weekly Synthesis Template]]

            ```query
            path:"70 Journal/Daily"
            ```
            """
        ),
        overwrite,
    )

    write_file(
        vault / "90 Templates" / "Daily Note.md",
        textwrap.dedent(
            """
            ---
            type: journal
            area:
            status: active
            date: {{date}}
            source: daily note
            confidence:
            tags:
              - journal
              - inbox
            ---

            # {{date}}

            ## Capture
            - #inbox

            ## Distill

            ## Decide

            ## Ship

            ## Learn

            ## Linked notes
            - [[00 Journal Hub]]
            - [[Intelligence Home]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "90 Templates" / "Web Capture Template.md",
        textwrap.dedent(
            """
            ---
            type: capture
            area:
            status: inbox
            date: {{date}}
            source:
            confidence:
            tags:
              - inbox
              - capture
            ---

            # {{title}}

            ## Source URL

            ## Why this matters

            ## Highlights

            ## Next best durable note
            - [[Insight - ]]
            - [[Problem - ]]
            - [[Initiative - ]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "90 Templates" / "Weekly Synthesis Template.md",
        textwrap.dedent(
            """
            ---
            type: review
            area:
            status: active
            date: {{date}}
            source: weekly synthesis
            confidence: high
            tags:
              - weekly-review
            ---

            # Weekly Synthesis - {{date}}

            ## Empty Inbox

            ## Durable Notes Created

            ## Active Bets Updated

            ## New Decisions

            ## Outcome Links Added

            ## Linked notes
            - [[Intelligence Home]]
            - [[TRAVERSAL-INDEX]]
            """
        ),
        overwrite,
    )

    write_file(vault / "80 Assets" / "Canvas" / "Intelligence Map.canvas", intelligence_canvas(mode), overwrite)

    folder_roles = [
        "- `00 Home/`: primary dashboards and navigation",
        "- `70 Journal/`: capture and weekly synthesis",
        "- `80 Assets/`: Bases and Canvas artifacts",
        "- `90 Templates/`: reusable note templates",
    ]
    start_lines = ["- [[00 Home/Intelligence Home]]", "- [[70 Journal/00 Journal Hub]]"]
    if mode in {"product", "hybrid"}:
        start_lines.extend(["- [[00 Home/Product OS]]", "- [[40 Research/00 Research Hub]]"])
        folder_roles.extend(
            [
                "- `10 Areas/`: durable domains or surfaces",
                "- `20 Problems/`: user or system problems",
                "- `30 Initiatives/`: active bets and efforts",
                "- `40 Research/`: raw and synthesized source material",
                "- `50 Decisions/`: explicit product or operating choices",
                "- `60 Experiments/`: tests, rollouts, and outcomes",
            ]
        )
    if mode in {"operations", "hybrid"}:
        start_lines.append("- [[Operations/INDEX]]")
        folder_roles.extend(
            [
                "- `Knowledge/`: books, frameworks, principles, concepts, and MOCs",
                "- `Operations/`: entities, summaries, playbooks, and hub nodes",
            ]
        )

    traversal_lines = [
        "---",
        "type: index",
        f'area: "{project}"',
        "status: active",
        "source: scaffold",
        "confidence: high",
        "tags:",
        "  - traversal-index",
        "---",
        "# TRAVERSAL-INDEX",
        "",
        f"Vault: {project}",
        "",
        "## Start Here",
    ]
    traversal_lines.extend(start_lines)
    traversal_lines.extend(
        [
            "",
            "## Folder Roles",
        ]
    )
    traversal_lines.extend(folder_roles)
    traversal_lines.extend(
        [
            "",
            "## Agent Guidance",
            "Read [[CLAUDE]] before making structural edits.",
        ]
    )
    write_file(vault / "TRAVERSAL-INDEX.md", "\n".join(traversal_lines), overwrite)

    nav_lines = [
        "1. Read `TRAVERSAL-INDEX.md`.",
        "2. Read `00 Home/Intelligence Home.md`.",
    ]
    if mode in {"product", "hybrid"}:
        nav_lines.append("3. Read `00 Home/Product OS.md` for product-memory work.")
    if mode in {"operations", "hybrid"}:
        nav_lines.append("4. Read `Operations/INDEX.md` for operations work.")
    nav_lines.append("5. Scan summaries and hub notes before reading deep source notes.")

    claude_lines = [
        "---",
        "type: policy",
        f'area: "{project}"',
        "status: active",
        "source: scaffold",
        "confidence: high",
        "tags:",
        "  - agent-schema",
        "---",
        f"# {project} Vault Agent Schema",
        "",
        "## Purpose",
        f"This vault is an intelligence system for {project}. Treat it as a synthesis layer, not a write-only archive.",
        "",
        "## Non-negotiable rules",
        "1. Every markdown file needs YAML frontmatter.",
        "2. Every note should connect to the graph with at least one wikilink.",
        "3. Hub nodes aggregate; leaf notes contain.",
        "4. Preserve raw material in `40 Research/` or `Knowledge/`.",
        "5. Never overwrite playbooks; create timestamped versions.",
        "",
        "## Navigation protocol",
    ]
    claude_lines.extend(nav_lines)
    claude_lines.extend(
        [
            "",
            "## Update rules",
            "- Keep dashboards and traversal notes current after large moves.",
            "- Patch stale query blocks if folders change.",
            "- Prefer adding new durable notes over appending large raw dumps to old notes.",
            "",
            "## Primary links",
            "- [[Intelligence Home]]",
            "- [[TRAVERSAL-INDEX]]",
        ]
    )
    write_file(vault / "CLAUDE.md", "\n".join(claude_lines), overwrite)


def scaffold_product(vault: Path, project: str, overwrite: bool) -> None:
    product_dirs = [
        vault / "10 Areas" / "Metrics",
        vault / "20 Problems",
        vault / "30 Initiatives",
        vault / "40 Research" / "Sources",
        vault / "40 Research" / "Insights",
        vault / "40 Research" / "Maps",
        vault / "40 Research" / "External Links",
        vault / "40 Research" / "Engineering Intelligence",
        vault / "50 Decisions",
        vault / "60 Experiments",
    ]
    for directory in product_dirs:
        directory.mkdir(parents=True, exist_ok=True)

    write_file(
        vault / "00 Home" / "Product OS.md",
        textwrap.dedent(
            f"""
            ---
            type: hub
            area: "{project}"
            status: active
            source: scaffold
            confidence: high
            tags:
              - product-os
            ---
            # Product OS

            Use this dashboard for product-memory work: what matters, why it matters, what is being tested, and what changed.

            Core notes:
            - [[Areas]]
            - [[Decision Log]]
            - [[Active Bets]]
            - [[Weekly Synthesis]]
            - [[Workspace Guide]]
            - [[00 Research Hub]]
            - [[00 Journal Hub]]

            Templates:
            - [[Decision Note Template]]
            - [[Initiative Note Template]]
            - [[Problem Note Template]]
            - [[Insight Note Template]]
            - [[Experiment Note Template]]
            - [[Metric Note Template]]
            - [[Web Capture Template]]
            - [[Daily Note]]
            - [[Weekly Synthesis Template]]

            ## Focus Stack
            ![[80 Assets/Bases/Initiatives.base#Active Bets]]

            ![[80 Assets/Bases/Problems.base#Open Problems]]

            ![[80 Assets/Bases/Inbox.base#Inbox]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "00 Home" / "Areas.md",
        textwrap.dedent(
            """
            ---
            type: hub
            area: product
            status: active
            source: scaffold
            confidence: high
            tags:
              - areas
            ---
            # Areas

            Durable product domains live here.

            ![[80 Assets/Bases/Areas.base#Areas]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "00 Home" / "Decision Log.md",
        textwrap.dedent(
            """
            ---
            type: hub
            area: product
            status: active
            source: scaffold
            confidence: high
            tags:
              - decisions
            ---
            # Decision Log

            Capture meaningful product or operating choices here.

            ![[80 Assets/Bases/Decisions.base#Recent Decisions]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "00 Home" / "Active Bets.md",
        textwrap.dedent(
            """
            ---
            type: hub
            area: product
            status: active
            source: scaffold
            confidence: high
            tags:
              - initiatives
            ---
            # Active Bets

            ![[80 Assets/Bases/Initiatives.base#Active Bets]]

            ## Experiments
            ![[80 Assets/Bases/Experiments.base#Experiments]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "00 Home" / "Weekly Synthesis.md",
        textwrap.dedent(
            """
            ---
            type: hub
            area: product
            status: active
            source: scaffold
            confidence: high
            tags:
              - weekly-review
            ---
            # Weekly Synthesis

            Weekly loop:
            - empty `#inbox`
            - turn raw capture into durable notes
            - update initiative pages
            - record new decisions
            - link outcomes back to metrics and problems

            Related notes:
            - [[Decision Log]]
            - [[Weekly Synthesis Template]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "00 Home" / "Workspace Guide.md",
        textwrap.dedent(
            """
            ---
            type: hub
            area: workspace
            status: active
            source: scaffold
            confidence: high
            tags:
              - workspace
            ---
            # Workspace Guide

            Suggested saved layouts:
            - Capture: daily note + backlinks + tags
            - Research: research hub + search + graph
            - Build: Product OS + Active Bets + code or research note

            Related notes:
            - [[Product OS]]
            - [[00 Research Hub]]
            - [[00 Journal Hub]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "40 Research" / "00 Research Hub.md",
        textwrap.dedent(
            """
            ---
            type: hub
            area: research
            status: active
            source: scaffold
            confidence: high
            tags:
              - research
            ---
            # 00 Research Hub

            Keep raw and synthesized source material here.

            ## Sources
            ```query
            path:"40 Research/Sources"
            ```

            ## Insights
            ![[80 Assets/Bases/Insights.base#Research Signals]]

            ## Engineering Intelligence
            ```query
            path:"40 Research/Engineering Intelligence"
            ```
            """
        ),
        overwrite,
    )

    templates = {
        "Decision Note Template.md": textwrap.dedent(
            """
            ---
            type: decision
            area:
            status: proposed
            date: {{date}}
            metric:
            tags:
              - decision
            ---

            # {{title}}

            ## Context

            ## Options considered

            ## Decision

            ## Expected impact

            ## Evidence
            - [[Insight - ]]

            ## Linked notes
            - [[Problem - ]]
            - [[Initiative - ]]
            - [[Metric - ]]
            """
        ),
        "Initiative Note Template.md": textwrap.dedent(
            """
            ---
            type: initiative
            area:
            status: active
            date: {{date}}
            metric:
            tags:
              - initiative
            ---

            # {{title}}

            ## Why this matters

            ## Hypothesis

            ## Success metric

            ## Risks

            ## Related decisions
            - [[Decision - ]]

            ## Related evidence
            - [[Insight - ]]
            - [[Experiment - ]]

            ## Next review
            """
        ),
        "Problem Note Template.md": textwrap.dedent(
            """
            ---
            type: problem
            area:
            status: active
            date: {{date}}
            metric:
            source:
            confidence:
            tags:
              - problem
            ---

            # {{title}}

            ## Why this matters

            ## Symptoms

            ## Where it shows up

            ## Related evidence
            - [[Insight - ]]

            ## Related bets
            - [[Initiative - ]]
            """
        ),
        "Insight Note Template.md": textwrap.dedent(
            """
            ---
            type: insight
            area:
            status: distilled
            date: {{date}}
            metric:
            source:
            confidence:
            tags:
              - insight
            ---

            # {{title}}

            ## Signal

            ## Why it matters

            ## Evidence

            ## Related problem
            - [[Problem - ]]

            ## Related initiative
            - [[Initiative - ]]
            """
        ),
        "Experiment Note Template.md": textwrap.dedent(
            """
            ---
            type: experiment
            area:
            status: proposed
            date: {{date}}
            metric:
            source:
            confidence:
            tags:
              - experiment
            ---

            # {{title}}

            ## Hypothesis

            ## Change

            ## Success metric

            ## Rollout plan

            ## Linked notes
            - [[Initiative - ]]
            - [[Decision - ]]
            """
        ),
        "Metric Note Template.md": textwrap.dedent(
            """
            ---
            type: metric
            area:
            status: tracking
            date: {{date}}
            source:
            confidence:
            tags:
              - metric
            ---

            # {{title}}

            ## Definition

            ## Why it matters

            ## Leading indicators

            ## Related notes
            - [[Problem - ]]
            - [[Initiative - ]]
            """
        ),
    }
    for name, content in templates.items():
        write_file(vault / "90 Templates" / name, content, overwrite)

    base_files = {
        "Areas.base": base_text("area", "Areas", ["file.name", "status", "metric", "confidence"]),
        "Problems.base": textwrap.dedent(
            """
            filters: 'type == "problem"'
            properties:
              file.name:
                displayName: Name
              area:
                displayName: Area
              status:
                displayName: Status
              metric:
                displayName: Metric
              confidence:
                displayName: Confidence
            views:
              - type: table
                name: "Open Problems"
                filters: 'status != "resolved"'
                order:
                  - file.name
                  - area
                  - status
                  - metric
                  - confidence
            """
        ).strip(),
        "Initiatives.base": textwrap.dedent(
            """
            filters: 'type == "initiative"'
            properties:
              file.name:
                displayName: Name
              area:
                displayName: Area
              status:
                displayName: Status
              metric:
                displayName: Metric
            views:
              - type: table
                name: "Active Bets"
                filters: 'status == "active" || status == "proposed"'
                order:
                  - file.name
                  - area
                  - status
                  - metric
            """
        ).strip(),
        "Decisions.base": base_text("decision", "Recent Decisions", ["file.name", "area", "status", "date"]),
        "Experiments.base": base_text("experiment", "Experiments", ["file.name", "area", "status", "metric"]),
        "Metrics.base": base_text("metric", "Metrics", ["file.name", "area", "status"]),
        "Insights.base": base_text("insight", "Research Signals", ["file.name", "area", "confidence"]),
        "Inbox.base": inbox_base_text(),
    }
    for name, content in base_files.items():
        write_file(vault / "80 Assets" / "Bases" / name, content, overwrite)


def scaffold_operations(
    vault: Path,
    project: str,
    entity_singular: str,
    entity_plural: str,
    overwrite: bool,
) -> None:
    entity_folder = title_case(entity_plural)
    operations_dirs = [
        vault / "Knowledge" / "Books",
        vault / "Knowledge" / "Frameworks",
        vault / "Knowledge" / "Concepts",
        vault / "Knowledge" / "Principles",
        vault / "Knowledge" / "Mental-Models",
        vault / "Knowledge" / "MOCs",
        vault / "Operations" / "_nodes" / "Status",
        vault / "Operations" / "_nodes" / "Categories",
        vault / "Operations" / "_nodes" / "Sentiments",
        vault / "Operations" / "_nodes" / "Pain-Points",
        vault / "Operations" / entity_folder,
    ]
    for directory in operations_dirs:
        directory.mkdir(parents=True, exist_ok=True)

    write_file(
        vault / "Operations" / "INDEX.md",
        textwrap.dedent(
            f"""
            ---
            type: hub
            area: operations
            status: active
            source: scaffold
            confidence: high
            tags:
              - operations
            ---
            # Operations Index

            This is the operational intelligence layer for {project}.

            Start here:
            - [[Operations/RULES]]
            - [[Knowledge/MOCs/Operations Intelligence MOC]]
            - [[Operations/_nodes/Status]]
            - [[Operations/{entity_folder}]]

            Templates:
            - [[Entity Intelligence Summary Template]]
            - [[Hub Node Template]]
            - [[Playbook Template]]
            - [[Knowledge Note Template]]
            - [[Weekly Dashboard Template]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "Operations" / "RULES.md",
        textwrap.dedent(
            f"""
            ---
            type: rules
            area: operations
            status: active
            source: scaffold
            confidence: high
            tags:
              - rules
            ---
            # Operations Rules

            - Every {entity_singular} should eventually have an `_intelligence_summary.md`.
            - Every summary needs frontmatter and graph connections.
            - Hub nodes aggregate shared dimensions.
            - Use timestamped playbooks. Never overwrite prior strategy.
            - Keep emails, transcripts, and tickets close to the relevant {entity_singular}.

            Related notes:
            - [[Operations/INDEX]]
            - [[Entity Intelligence Summary Template]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "Knowledge" / "MOCs" / "Operations Intelligence MOC.md",
        textwrap.dedent(
            """
            ---
            type: moc
            description: "Bridge knowledge notes to operational situations"
            tags:
              - moc
            ---
            # Operations Intelligence MOC

            ## When an entity is At Risk
            - [[Framework - ]]

            ## When planning growth
            - [[Framework - ]]

            ## When preparing a difficult conversation
            - [[Framework - ]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "90 Templates" / "Entity Intelligence Summary Template.md",
        textwrap.dedent(
            """
            ---
            type: intelligence-summary
            entity:
            category:
            status:
            primary_contact:
            last_updated: {{date}}
            tags: []
            ---

            # {{title}}

            ## Overview

            ## Key Contacts

            ## Account Notes / Context

            ## Active Issues

            ## Graph Connections
            **Category:** [[ ]]
            **Status:** [[ ]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "90 Templates" / "Hub Node Template.md",
        textwrap.dedent(
            """
            ---
            type: node
            node_type:
            title:
            entity_count:
            description:
            ---

            # {{title}}

            ## Connected Entities

            ## Related Dimensions
            - [[Operations/INDEX]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "90 Templates" / "Playbook Template.md",
        textwrap.dedent(
            """
            ---
            type: playbook
            entity:
            date: {{date}}
            status:
            scenario_selected:
            tags:
              - playbook
            ---

            # {{title}}

            ## Situation

            ## Recommended actions

            ## Risks

            ## Linked notes
            - [[_intelligence_summary]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "90 Templates" / "Knowledge Note Template.md",
        textwrap.dedent(
            """
            ---
            type: framework
            description:
            source:
            tags: []
            aliases: []
            ---

            # {{title}}

            ## Summary

            ## When to use it

            ## Related notes
            - [[Operations Intelligence MOC]]
            """
        ),
        overwrite,
    )

    write_file(
        vault / "90 Templates" / "Weekly Dashboard Template.md",
        textwrap.dedent(
            """
            ---
            type: dashboard
            date: {{date}}
            tags:
              - dashboard
            ---

            # Weekly Dashboard - {{date}}

            ## Silent Entities

            ## Status Changes

            ## New Risks

            ## Recommended Follow-up
            - [[Operations/INDEX]]
            """
        ),
        overwrite,
    )

    entity_base = textwrap.dedent(
        """
        filters: 'type == "intelligence-summary"'
        properties:
          file.name:
            displayName: Name
          entity:
            displayName: Entity
          category:
            displayName: Category
          status:
            displayName: Status
          last_updated:
            displayName: Last Updated
        views:
          - type: table
            name: "Entities"
            order:
              - entity
              - category
              - status
              - last_updated
        """
    ).strip()
    write_file(vault / "80 Assets" / "Bases" / "Entities.base", entity_base, overwrite)

    nodes_base = textwrap.dedent(
        """
        filters: 'type == "node"'
        properties:
          file.name:
            displayName: Name
          node_type:
            displayName: Node Type
          title:
            displayName: Title
          entity_count:
            displayName: Entity Count
        views:
          - type: table
            name: "Hub Nodes"
            order:
              - node_type
              - title
              - entity_count
        """
    ).strip()
    write_file(vault / "80 Assets" / "Bases" / "Nodes.base", nodes_base, overwrite)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold an Obsidian intelligence vault.")
    parser.add_argument("--vault", required=True, help="Absolute path to the vault.")
    parser.add_argument("--project", required=True, help="Project or system name.")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["product", "operations", "hybrid"],
        help="Which topology to scaffold.",
    )
    parser.add_argument("--entity-singular", default="entity", help="Singular name for operational entities.")
    parser.add_argument("--entity-plural", default="entities", help="Plural name for operational entities.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing scaffold files.")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    vault.mkdir(parents=True, exist_ok=True)

    scaffold_common(vault, args.project, args.mode, args.overwrite)

    if args.mode in {"product", "hybrid"}:
        scaffold_product(vault, args.project, args.overwrite)

    if args.mode in {"operations", "hybrid"}:
        scaffold_operations(
            vault,
            args.project,
            args.entity_singular,
            args.entity_plural,
            args.overwrite,
        )


if __name__ == "__main__":
    main()
