# Workflow

This is the generic operating model the package is designed to prove.

## Phase 1. Prepare the product boundary

Decide:
- product name
- product slug
- vault path
- workspace path
- mode: `product`, `operations`, or `hybrid`

If you are unsure, use `hybrid`.

## Phase 2. Create the manifest

The manifest is the contract for the whole system. It defines:
- product identity
- source paths
- repositories
- automation pack ids
- engineering-readiness categories

Do not skip this. The manifest is what makes the approach reusable instead of ad hoc.

## Phase 3. Scaffold the vault

Use the bootstrap script or the packaged scaffold script to create:
- home dashboards
- research layer
- journal
- templates
- Bases
- Canvas
- starter audit note

At this point, the vault exists before heavy ingestion starts.

## Phase 4. Add real sources

Typical source material:
- repositories
- product docs
- support exports
- markdown files
- PDFs
- DOCX files
- internal notes
- external links

Preserve raw material first. Synthesize after capture.

## Phase 5. Use Codex to build the second brain

Use Codex with:
- `product-intelligence-factory` for the scale boundary
- `obsidian-intelligence-system` for the vault and synthesis layer
- `product-engineering-ops` for engineering readiness

Expected outputs:
- linked notes
- code-intelligence layer
- problem and initiative notes
- conflicts when docs and code disagree
- audit and readiness reports

## Phase 6. Prove engineering value

A good proof run should show at least one of these:
- a doc-to-code trace
- a bug candidate with supporting context
- a local runtime or repo map
- an explicit readiness gap report

## Phase 7. Add recurring automations

Only after the manual flow works, add the standard automation pack:
- source-truth sync
- PR merge sync
- repo mirror sync
- readiness audit

## Phase 8. Scale to product 2

Once the first product works:
- keep the skills generic
- reuse the prompts
- create a new manifest
- avoid one-off product-specific logic unless truly necessary
