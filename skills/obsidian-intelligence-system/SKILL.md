---
name: obsidian-intelligence-system
description: Scaffold, audit, and evolve an Obsidian vault into a reusable intelligence system or product second brain. Use when a user wants to turn project documents, repos, links, notes, PDFs, or recurring entity records into a linked vault with YAML frontmatter, internal links, dashboards, templates, Bases, Canvas, hub nodes, intelligence summaries, and research-to-action synthesis.
---

# Obsidian Intelligence System

## Overview

Use this skill when the goal is not just to store notes in Obsidian, but to turn a vault into a working memory system for a project, team, product, research corpus, or operational portfolio.

When the user is trying to scale this beyond one product, pair this skill with:
- `$CODEX_HOME/skills/product-intelligence-factory/SKILL.md`
- `$CODEX_HOME/skills/product-engineering-ops/SKILL.md`

This skill supports three patterns:
- `product`: a product-memory layer built around areas, problems, initiatives, decisions, experiments, metrics, and distilled research.
- `operations`: a Jay Khalife style intelligence system with `Knowledge/`, `Operations/`, hub nodes, entity intelligence summaries, and timestamped playbooks.
- `hybrid`: both layers together, with research and frameworks feeding operational or product decisions.

Read [references/runbook.md](references/runbook.md) when you need the operational topology from the PDF. Read [references/schemas.md](references/schemas.md) when you need the note types, required properties, and template shapes.

## Workflow

### 1. Inspect the vault and source material first

- Identify whether the vault already exists, is partially structured, or is just a raw folder.
- Inspect the source corpus before editing anything: markdown, PDFs, DOCX, exported help docs, URLs, repos, meeting notes, tickets, or email exports.
- Decide the mode:
  - `product` if the user mostly needs synthesis, reasoning, and product judgment.
  - `operations` if the user manages recurring real-world entities such as customers, campuses, projects, cases, or portfolios.
  - `hybrid` if both are true.

### 2. Scaffold the vault before heavy synthesis

Use the scaffold script to create the repeatable structure and Obsidian config:

```bash
python3 scripts/scaffold_vault.py \
  --vault "/absolute/path/to/vault" \
  --project "Project Name" \
  --mode hybrid \
  --entity-singular customer \
  --entity-plural customers
```

The scaffold creates:
- Official/core Obsidian settings for Properties, Daily Notes, Templates, Backlinks, Search, Canvas, Workspaces, and Bases.
- Product-memory zones such as `00 Home`, `10 Areas`, `20 Problems`, `30 Initiatives`, `40 Research`, `50 Decisions`, `60 Experiments`, `70 Journal`, `80 Assets`, and `90 Templates`.
- Operations zones such as `Knowledge/`, `Operations/`, and `Operations/_nodes/`.
- `CLAUDE.md` and `TRAVERSAL-INDEX.md` seeds so agents and humans have a navigation contract.
- Valid `.base` files, templates, and a starter canvas.

When the user already has a vault, preserve useful material and move raw or imported content into the research or knowledge layer instead of deleting it.

### 3. Ingest sources without losing provenance

- Preserve raw material in `40 Research` or `Knowledge/Books|Frameworks|Concepts|...`.
- If a source is authenticated or externally linked, capture enough context to make the note usable offline.
- Prefer one note per durable concept, entity, problem, decision, or experiment.
- When importing from an existing vault, patch stale queries and legacy home notes after any folder moves.

### 4. Build the graph deliberately

These rules are non-negotiable:
- Every Markdown file should have YAML frontmatter.
- Every note should have at least one wikilink.
- Hub nodes aggregate; leaf nodes contain.
- Use links for durable nouns and tags for workflow states such as `#inbox`, `#to-review`, `#decision-needed`, and `#risk`.
- Never overwrite playbooks or action plans; create timestamped versions.

For `product` and `hybrid` mode:
- Create area, problem, initiative, metric, decision, experiment, and insight notes.
- Keep raw research in `40 Research`.
- Use `Product OS`, `Areas`, `Decision Log`, and `Active Bets` as the main dashboards.

For `operations` and `hybrid` mode:
- Create one `_intelligence_summary.md` per real-world entity.
- Create hub nodes in `Operations/_nodes/` for the dimensions the user actually filters by.
- Use `Knowledge/MOCs/` to bridge knowledge-layer frameworks to operational situations.
- Keep each entity folder as a living intelligence space for emails, transcripts, tickets, and timestamped playbooks.

### 5. Add code intelligence when repos matter

If the source corpus includes repositories, create a code-intelligence layer adjacent to research:
- Repo notes with purpose, stack, key files, and representative code.
- Product-to-code or operations-to-code maps.
- Architecture deep dives or playbooks for recurring workflows.
- Links from product problems or operational issues back to the relevant repos and files.

This layer belongs in research, not as a replacement for product or operational reasoning.

### 6. Maintain the vault as a synthesis layer

- Use Daily Notes as the capture inbox.
- Distill raw capture into durable notes at least weekly.
- Keep delivery in the system of record such as GitHub, Jira, or Linear; Obsidian should store the reasoning, evidence, and intelligence around the work.
- Revisit `CLAUDE.md`, `TRAVERSAL-INDEX.md`, dashboards, and hub nodes as the vault evolves.

### 7. Audit after every substantial change

Run the audit script before finishing:

```bash
python3 scripts/audit_vault.py --vault "/absolute/path/to/vault"
```

Use `--write` to save a report into the vault:

```bash
python3 scripts/audit_vault.py \
  --vault "/absolute/path/to/vault" \
  --write "/absolute/path/to/vault/80 Assets/vault-audit.md"
```

The audit checks:
- Missing frontmatter
- Missing wikilinks
- Missing required fields for known note types
- Duplicate stems that can make wikilinks ambiguous
- Orphan candidates with no inbound or outbound graph connections

### 8. Propagate source-of-truth changes into specialization vaults

When this skill changes, any specialization built on top of it should be treated as stale until its vault is refreshed.

- Treat the skill source of truth as the combination of:
  - `SKILL.md`
  - `references/`
  - `scripts/`
  - `agents/`
- Specializations should watch both this general skill directory and their own specialization directory.
- Use a hash-based change detector so local edits and pulled PR merges are both caught once the source-of-truth files land locally.
- Only update the saved watcher state after the specialization refresh pipeline succeeds.
- Prefer an automation for this instead of relying on memory. The automation should run the specialization refresh script, not try to rebuild the vault ad hoc.

### 9. Prefer manifests over custom per-product workflows when scaling

If the user is trying to onboard many products, this skill should not become the only place where product-specific logic lives.

- Put product identity, sources, repos, automation ids, and readiness categories into a manifest.
- Keep this skill generic.
- Push scaling concerns into the product factory layer instead of copying and pasting one-off product workflows.

## What this skill should usually produce

- A structured vault with clear entry points
- A research or knowledge layer that preserves provenance
- A product-memory or operations-intelligence layer that is actually navigable
- Templates and Bases views so the vault stays consistent
- A CLAUDE-style agent schema and traversal index
- An audit report or a final cleanup pass that removes structural blind spots

## Example requests

- "Turn these PDFs, docs, and repos into an Obsidian second brain for our product."
- "Create a customer intelligence system in Obsidian for our campus portfolio."
- "Reorganize this vault into research, decisions, initiatives, and experiments without losing the imported notes."
- "Use this support export plus GitHub repos to build a linked product-memory vault."
