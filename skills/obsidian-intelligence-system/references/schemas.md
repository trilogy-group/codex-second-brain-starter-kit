# Obsidian Intelligence Schemas

Use these schemas when the user wants a repeatable vault structure rather than ad hoc notes.

## Product-memory note types

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
