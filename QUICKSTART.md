# Quickstart

This is the shortest path to test the approach on your own product.

## 1. Install the skills into Codex

```bash
cd /absolute/path/to/codex-second-brain-starter-kit
./scripts/install_codex_starter.sh
```

This copies the bundled generic skills into `${CODEX_HOME:-$HOME/.codex}/skills`.

## 2. Initialize a multi-brain portfolio

Replace the placeholders below with your own values:

```bash
./scripts/second_brain_wizard.py init-portfolio \
  --portfolio-root "/absolute/path/to/second-brain-portfolio" \
  --name "Acme Product Portfolio" \
  --obsidian-root "/absolute/path/to/Obsidian/Product Brains"
```

What this creates:
- a portfolio registry
- shared roots for workspaces, manifests, and default vault locations
- a repeatable starting point for multiple second brains

## 3. Add your first second brain

```bash
./scripts/second_brain_wizard.py add-brain \
  --portfolio-root "/absolute/path/to/second-brain-portfolio" \
  --name "Acme Platform" \
  --slug "acme-platform" \
  --mode hybrid
```

What this creates:
- a starter manifest
- a scaffolded Obsidian vault
- a first vault audit
- a first engineering-readiness report

## 4. Put real material into the workspace

Open the generated manifest and place your real source material in the paths it describes:
- `sources.corpus_path`
- `repositories.local_clone_root`

Then replace the sample repository entries with your actual repositories.

## 5. Validate the manifest

```bash
python3 ./skills/product-intelligence-factory/scripts/validate_product_manifest.py \
  --manifest "/absolute/path/to/second-brain-portfolio/manifests/acme-platform.yaml" \
  --check-paths
```

## 6. Open Codex and use the starter prompts

Recommended order:
1. `prompts/01_bootstrap_product.md`
2. `prompts/02_ingest_and_build_second_brain.md`
3. `prompts/03_build_engineering_layer.md`
4. `prompts/04_bug_workflow.md`
5. `prompts/05_create_automations.md`
6. `prompts/06_review_readiness.md`

## 7. Prove the workflow before scaling it

A good first test should end with:
- a usable Obsidian home note
- linked research and engineering notes
- at least one code-intelligence path from docs to code
- a real readiness report
- a clear list of what is still manual

## Helpful wizard commands

```bash
./scripts/second_brain_wizard.py list-brains --portfolio-root "/absolute/path/to/second-brain-portfolio"
./scripts/second_brain_wizard.py doctor --portfolio-root "/absolute/path/to/second-brain-portfolio"
./scripts/second_brain_wizard.py refresh --portfolio-root "/absolute/path/to/second-brain-portfolio"
```
