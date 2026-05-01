# Obsidian Intelligence Schemas

Use these schemas when the user wants a repeatable vault structure rather than ad hoc notes.

## Product-memory note types

Durable product notes should also carry Product BASB metadata:
- `basb_stage: capture | organize | distill | express | archive`
- `para_category: project | area | resource | archive`
- `distillation_level: raw | highlighted | distilled | executive`
- `actionability: now | soon | someday | reference`
- `output_target` when the note feeds a spec, ticket, PR, runbook, launch artifact, or other shippable output

Generated lifecycle notes add:
- `output_kind: prd | spec | ticket | pull-request-plan | runbook | decision | launch-note | post-launch-learning`
- `source_packet`
- `evidence_score`
- `shipping_path`
- `review_period`
- `archive_reason`

### Area

Required:
- `type: area`
- `area`
- `status`
- `date`

Typical use:
- durable product surface or operating domain

### Problem

Required:
- `type: problem`
- `area`
- `status`
- `date`

Optional:
- `metric`
- `source`
- `confidence`

### Initiative

Required:
- `type: initiative`
- `area`
- `status`
- `date`

Optional:
- `metric`
- `source`
- `confidence`

### Decision

Required:
- `type: decision`
- `area`
- `status`
- `date`

### Experiment

Required:
- `type: experiment`
- `area`
- `status`
- `date`

### Metric

Required:
- `type: metric`
- `area`
- `status`
- `date`

### Insight

Required:
- `type: insight`
- `area`
- `status`
- `date`

### Intermediate packet

Required:
- `type: intermediate-packet`
- `area`
- `status`
- `date`
- `basb_stage`
- `para_category`
- `distillation_level`
- `actionability`

Typical use:
- reusable research briefs, support-to-code traces, code investigations, bug hypotheses, or launch/runbook fragments

### Output

Required:
- `type: output`
- `area`
- `status`
- `date`
- `basb_stage`
- `para_category`
- `distillation_level`
- `actionability`
- `source_packet`
- `evidence_score`
- `shipping_path`

Typical use:
- PRD, spec, ticket, PR, runbook, decision, launch note, or post-launch learning record

Optional:
- `output_target`
- `output_kind`

### Archive record

Required:
- `type: archive-record`
- `area`
- `status`
- `date`
- `basb_stage`
- `para_category`
- `archive_reason`

Typical use:
- closeout notes for completed initiatives, retired decisions, stale source snapshots, and reusable project learnings

### Review

Required:
- `type: review`
- `area`
- `status`
- `date`
- `review_period`
- `basb_stage`
- `para_category`

Typical use:
- weekly Product BASB review notes that summarize packets, output candidates, stale sources, and next actions

## Operations note types

### Intelligence summary

Required:
- `type: intelligence-summary`
- `entity`
- `category`
- `status`
- `last_updated`

Typical sections:
- overview
- key contacts
- account or context notes
- active issues
- graph connections

### Hub node

Required:
- `type: node`
- `node_type`
- `title`

Optional:
- `description`
- `entity_count`

### Playbook

Required:
- `type: playbook`
- `entity`
- `date`

Optional:
- `status`
- `scenario_selected`

### Knowledge note

Required:
- `type`
- `description`
- `tags`

Optional:
- `source`
- `author`
- `aliases`

Typical values for `type`:
- `book`
- `framework`
- `concept`
- `principle`
- `mental-model`
- `moc`

## Graph rules

- Use wikilinks for durable nouns.
- Use tags for handling states.
- Prefer stable file stems to reduce ambiguous links.
- Keep raw source material in a research or knowledge layer.
- Let hub notes aggregate and summary notes interpret.

## Product-memory templates

### Decision note

```yaml
---
type: decision
area:
status: proposed
date: {{date}}
metric:
tags:
  - decision
---
```

### Initiative note

```yaml
---
type: initiative
area:
status: active
date: {{date}}
metric:
tags:
  - initiative
---
```

### Intermediate packet note

```yaml
---
type: intermediate-packet
area:
status: reusable
date: {{date}}
basb_stage: distill
para_category: resource
distillation_level: executive
actionability: soon
output_target:
tags:
  - intermediate-packet
---
```

### Output note

```yaml
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
tags:
  - output
---
```

## Operations templates

### Intelligence summary

```yaml
---
type: intelligence-summary
entity:
category:
status:
primary_contact:
last_updated: {{date}}
tags: []
---
```

### Hub node

```yaml
---
type: node
node_type:
title:
entity_count:
description:
---
```

### Playbook

```yaml
---
type: playbook
entity:
date: {{date}}
status:
scenario_selected:
tags:
  - playbook
---
```
