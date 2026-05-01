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

## Phase 2. Create or initialize the portfolio

If you want to support multiple second brains, start with the wizard and create a portfolio root first.

The portfolio gives you:
- one registry for all second brains
- one consistent place for workspaces and manifests
- one default place for vaults

## Phase 3. Create the manifest

The manifest is the contract for the whole system. It defines:
- product identity
- source paths
- the intelligence profile path
- repositories
- automation pack ids
- engineering-readiness categories

Do not skip this. The manifest is what makes the approach reusable instead of ad hoc.

## Phase 4. Scaffold the vault

Use the bootstrap script or the packaged scaffold script to create:
- home dashboards
- CODE dashboard
- PARA map
- output pipeline
- intermediate packet and archive hubs
- research layer
- journal
- templates
- Bases
- Canvas
- starter audit note

At this point, the vault exists before heavy ingestion starts.

## Phase 5. Add real sources

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

## Phase 6. Run the Product BASB loop

Use Codex with:
- `product-intelligence-factory` for the scale boundary
- `obsidian-intelligence-system` for the vault and synthesis layer
- `product-engineering-ops` for engineering readiness

When the packaged helpers are available, run the source-index and rebuild flow before asking Codex to do the final synthesis pass:
- `python3 skills/product-intelligence-factory/scripts/build_source_indices.py --manifest "/absolute/path/to/product.yaml"`
- `OPENAI_API_KEY="..." python3 skills/product-intelligence-factory/scripts/rebuild_product_brain.py --manifest "/absolute/path/to/product.yaml"`

Expected outputs:
- linked notes
- Product BASB metadata across durable generated notes
- capture-quality scores
- Essence and Use in current project sections before full source content
- intermediate packets for reusable support, wiki, code, and planning clusters
- generated output candidates in `30 Initiatives/Output Candidates/`
- a weekly review note in `70 Journal/Reviews/`
- stale-source archive records in `90 Archive/Stale Sources/`
- code-intelligence maps in `40 Research/Code Intelligence/Maps/` and `40 Research/Code Intelligence/Graphs/`
- semantic intermediate packets in `40 Research/Intermediate Packets/`
- full support and wiki content preserved in-note
- problem and initiative notes
- code-reference notes with summaries, intent, relevance, risks, and conflicts
- explicit uncaptured-evidence sections when linked sources stay blocked
- conflicts when docs and code disagree
- audit and readiness reports

## Phase 7. Express into shippable work

A good proof run should show at least one of these:
- a doc-to-code trace
- a bug candidate with supporting context
- a local runtime or repo map
- an explicit readiness gap report
- a shippable output candidate such as a PRD, spec, ticket, PR plan, runbook, decision, launch note, or post-launch learning record

Version 1 creates Obsidian output drafts only. GitHub, Jira, Linear, and support tools remain the systems of record.

## Phase 8. Archive and reuse

After an initiative or investigation is complete:
- move completed project work into `30 Initiatives/Completed/` or `90 Archive/`
- preserve reusable intermediate packets in `40 Research/Intermediate Packets/`
- record what shipped, what was learned, and which sources are now stale
- keep delivery systems such as GitHub, Jira, or Linear as the system of record

For existing vaults, run the migration CLI in dry-run mode before applying changes:

```bash
python3 skills/obsidian-intelligence-system/scripts/migrate_to_product_basb.py \
  --vault "/absolute/path/to/vault" \
  --product-slug "product-slug"
```

## Phase 9. Add recurring automations

Only after the manual flow works, add the standard automation pack:
- source-truth sync
- PR merge sync
- repo mirror sync
- readiness audit

## Phase 10. Scale to product 2

Once the first product works:
- keep the skills generic
- reuse the prompts
- create a new manifest
- avoid one-off product-specific logic unless truly necessary
