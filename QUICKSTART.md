# Quickstart

This is the shortest path to test the approach on your own product.

## 1. Install the skills into Codex

```bash
cd /absolute/path/to/codex-second-brain-starter-kit
./scripts/install_codex_starter.sh
```

This copies the bundled generic skills into `${CODEX_HOME:-$HOME/.codex}/skills`.

## 2. Bootstrap a product workspace

Replace the placeholders below with your own values:

```bash
./scripts/bootstrap_test_workspace.sh \
  --name "Acme Platform" \
  --slug "acme-platform" \
  --mode hybrid \
  --vault "/absolute/path/to/Obsidian/Acme Platform" \
  --workspace "/absolute/path/to/acme-product-workspace"
```

What this creates:
- a starter manifest
- a scaffolded Obsidian vault
- a first vault audit
- a first engineering-readiness report

## 3. Put real material into the workspace

Open the generated manifest and place your real source material in the paths it describes:
- `sources.corpus_path`
- `repositories.local_clone_root`

Then replace the sample repository entries with your actual repositories.

## 4. Validate the manifest

```bash
python3 ./skills/product-intelligence-factory/scripts/validate_product_manifest.py \
  --manifest "/absolute/path/to/acme-product-workspace/manifests/acme-platform.yaml" \
  --check-paths
```

## 5. Open Codex and use the starter prompts

Recommended order:
1. `prompts/01_bootstrap_product.md`
2. `prompts/02_ingest_and_build_second_brain.md`
3. `prompts/03_build_engineering_layer.md`
4. `prompts/04_bug_workflow.md`
5. `prompts/05_create_automations.md`
6. `prompts/06_review_readiness.md`

## 6. Prove the workflow before scaling it

A good first test should end with:
- a usable Obsidian home note
- linked research and engineering notes
- at least one code-intelligence path from docs to code
- a real readiness report
- a clear list of what is still manual
