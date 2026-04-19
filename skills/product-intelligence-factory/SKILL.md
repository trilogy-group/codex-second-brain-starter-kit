---
name: product-intelligence-factory
description: Bootstrap, validate, and scale manifest-driven product intelligence systems that combine Obsidian, source ingestion, code intelligence, and recurring automations. Use when a user wants to onboard one product or many products into a repeatable second-brain workflow with low incremental human effort.
---

# Product Intelligence Factory

Use this skill when the goal is no longer "build one good vault," but "build a repeatable product-import system" that can onboard many products with the same operating model.

Read these references when needed:
- [references/manifest-schema.md](references/manifest-schema.md) for the product manifest contract.
- [references/automation-pack.md](references/automation-pack.md) for the recurring automation model.

This skill should usually be paired with:
- `$CODEX_HOME/skills/obsidian-intelligence-system/SKILL.md`
- `$CODEX_HOME/skills/product-engineering-ops/SKILL.md`

## Workflow

### 1. Start with a product manifest

Every product should be described by one manifest instead of one custom skill.

Create a starter manifest with:

```bash
python3 scripts/init_product_manifest.py \
  --output "/absolute/path/to/product.yaml" \
  --name "Product Name" \
  --slug "product-slug" \
  --mode hybrid \
  --vault "/absolute/path/to/vault" \
  --workspace "/absolute/path/to/workspace"
```

Validate an existing manifest with:

```bash
python3 scripts/validate_product_manifest.py \
  --manifest "/absolute/path/to/product.yaml" \
  --check-paths
```

Create or refresh the generic capability profile with:

```bash
python3 scripts/init_intelligence_profile.py \
  --output "/absolute/path/to/workspace/config/intelligence-profile.yaml"
```

### 2. Treat manifests as the scale boundary

The manifest should hold:
- product identity and vault/workspace paths
- source corpus paths and authenticated cache locations
- repository inventory
- safe mirror locations for repo sync
- automation ids
- engineering readiness categories and next steps

Do not fork the workflow per product unless a source type or auth flow is truly unique.

### 3. Use safe repo mirrors for automation-driven code sync

Automation should not hard-reset active worktrees. Sync repositories into a dedicated mirror root instead:

```bash
python3 scripts/sync_repo_mirrors.py \
  --manifest "/absolute/path/to/product.yaml"
```

This gives the system a refreshable code source of truth that does not disturb local feature branches.

### 4. Build inventories before synthesis

When real sources are present, prefer the packaged inventory builder before manual note synthesis:

```bash
python3 scripts/build_source_indices.py \
  --manifest "/absolute/path/to/product.yaml"
```

This stage should:
- preserve raw-source provenance
- extract DOCX text when available
- classify linked pages into mirrored, local evidence, restricted, or stale-documentation buckets
- generate source inventories and repo snapshots that the vault rebuild can consume

Then rebuild the vault with:

```bash
python3 scripts/rebuild_product_brain.py \
  --manifest "/absolute/path/to/product.yaml"
```

The rebuild should produce:
- full support and wiki note content, not thin summaries
- Obsidian wikilinks across support, wiki, repo, capability, and code-reference notes
- code-reference notes with intent, relevance, implementation signals, and risk/conflict summaries
- explicit blocker and uncaptured-evidence sections instead of silent omissions
- a privacy pass that redacts obvious PII from generated vault markdown

### 5. Keep the factory generic and specializations thin

The preferred layering is:
- one generic product-import factory
- one generic engineering-ops skill
- one generic Obsidian intelligence skill
- one manifest per product
- one optional product-specific specialization only when a product truly has custom logic

If a workflow can be moved into the manifest or a generic helper script, do that before creating a new product-specific skill.

### 6. Install the standard automation pack

Each product should normally have:
- skill source-of-truth sync
- merged PR refresh
- safe repo mirror sync
- recurring engineering-readiness audit

Use [references/automation-pack.md](references/automation-pack.md) to keep those automations consistent across products.

### 7. Produce a scale-readiness answer, not just a vault

When finishing, be explicit about:
- what is already automated
- what still depends on human intervention
- what is product-specific vs generic
- what must be generalized before onboarding 5 or 10 more products
