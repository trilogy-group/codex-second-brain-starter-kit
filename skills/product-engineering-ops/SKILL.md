---
name: product-engineering-ops
description: Build and audit engineering-ready product intelligence around services, local runtime, CI/CD, deployments, support-to-code workflows, and scale-readiness. Use when a user wants a product second brain that engineers can actually ship, debug, deploy, and support from.
---

# Product Engineering Ops

Use this skill when the vault must become a real engineering operating surface rather than only a knowledge repository.

Read [references/readiness-model.md](references/readiness-model.md) before building or auditing the engineering layer.

This skill is designed to work with:
- `$CODEX_HOME/skills/product-intelligence-factory/SKILL.md`
- `$CODEX_HOME/skills/obsidian-intelligence-system/SKILL.md`

## Workflow

### 1. Start from the manifest

Validate the manifest first:

```bash
python3 $CODEX_HOME/skills/product-intelligence-factory/scripts/validate_product_manifest.py \
  --manifest "/absolute/path/to/product.yaml" \
  --check-paths
```

### 2. Make engineering readiness explicit

Every product should be scored across at least these areas:
- reusable import factory readiness
- source ingestion and authenticated capture
- code and repo intelligence
- safe repo sync
- local runtime and feature work support
- bug/support-to-code workflow
- CI/CD and deployment intelligence
- automation coverage

Do not leave these as implicit tribal knowledge.

### 3. Generate a recurring readiness report

Use the report generator to render the current status from the manifest:

```bash
python3 scripts/generate_engineering_readiness.py \
  --manifest "/absolute/path/to/product.yaml" \
  --write "/absolute/path/to/report.md"
```

The output should clearly separate:
- what is done
- what is partial
- what is missing
- the next implementation steps

### 4. Drive the next implementation from the gaps

The report is not an archive. Use it to choose the next highest-leverage system work:
- if repo sync is missing, build mirror sync
- if CI/CD intelligence is missing, ingest workflows, environments, releases, and deploy runbooks
- if support-to-code is weak, connect support notes to code paths, tests, and repro flows
- if the workflow is still product-specific, move logic into the generic factory layer

### 5. Install a weekly readiness audit

Every product should have a recurring audit automation so scale blockers stay visible instead of being rediscovered manually.
