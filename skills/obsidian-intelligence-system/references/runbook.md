# Obsidian Intelligence System Runbook

This reference distills the Jay Khalife PDF into the parts that matter when building or rebuilding a vault.

## Core model

The runbook describes a two-layer system:
- `Knowledge Layer`: books, frameworks, mental models, principles, and concepts.
- `Operations Layer`: real-world entities such as customers, campuses, projects, or portfolios, each with a living intelligence file.

The value comes from linking them. The knowledge layer tells you what to do. The operations layer tells you what is happening.

## Non-negotiable rules

- Every Markdown file should have YAML frontmatter.
- Every file should connect to the graph with at least one wikilink.
- Hub nodes aggregate shared dimensions.
- Leaf notes hold the actual content and link back to hubs.
- Build for progressive disclosure: scan index notes first, then go deeper only when needed.
- Use consistent naming conventions.

## Recommended operational topology

```text
Knowledge/
  Books/
  Frameworks/
  Concepts/
  Principles/
  Mental-Models/
  MOCs/
Operations/
  INDEX.md
  RULES.md
  _nodes/
    Status/
    Categories/
    Sentiments/
    Pain-Points/
  <Entity Group>/
    <Entity Name>/
      _intelligence_summary.md
      Emails/
      Transcripts/
      Tickets/
      YYYY-MM-DD_Playbook.md
```

## Intelligence summary pattern

Each entity should have one entry-point note that captures:
- Machine-readable metadata
- A short current-state overview
- Key contacts
- Ongoing context or account notes
- Active issues
- Graph connections back to the relevant hub nodes

Common fields:
- `type`
- `entity`
- `category`
- `status`
- `last_updated`
- optionally `primary_contact`, `tags`, `renewal_date`, or similar domain-specific fields

## Hub nodes

Hub nodes are the graph backbone. They represent the dimensions the user filters by most often, such as:
- status
- category or type
- sentiment
- pain points
- success tier

Each hub node should:
- have frontmatter
- list the connected entities
- link to related dimensions

Do not make hub nodes too granular too early.

## Bridging knowledge to action

The bridge between knowledge and operations is usually a Map of Content:
- "When an entity is at risk, use these frameworks"
- "When planning expansion, use these frameworks"
- "When a conversation is tense, use these frameworks"

In practice:
1. Find the operational state.
2. Open the intelligence summary.
3. Use the MOC to locate the relevant frameworks.
4. Apply them in a timestamped playbook.

## Ingestion cadence

The runbook recommends a recurring sweep:
- emails
- meetings or transcripts
- tickets
- summary updates
- alert detection for silence, deadlines, or sentiment shifts

Consistency matters more than fancy automation.

## Agent schema

The PDF recommends a root `CLAUDE.md` so AI agents know:
- the system overview
- the folder structure
- file naming rules
- YAML requirements
- wikilink rules
- navigation protocol
- mandatory pre-reads
- data sources
- update rules

This is effectively the navigation contract for future agents.

## Implementation phases

- Phase 1: scaffold the vault and rules
- Phase 2: seed content and summaries
- Phase 3: build the knowledge layer and bridge MOCs
- Phase 4: add weekly ingestion or automation
- Phase 5: keep a feedback loop and measure outcomes

## Common failure modes

- Files with no wikilinks
- Missing frontmatter
- Hub nodes that are too granular
- Treating the vault as a write-only archive
- Overwriting playbooks instead of versioning them
- Building only knowledge or only operations and never connecting them
- Waiting for a perfect design before starting
