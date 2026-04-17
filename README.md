# Codex Second Brain Starter Kit

This is a generic Codex setup for testing the second-brain workflow on any codebase.

It packages:
- reusable Codex skills for product intelligence, Obsidian synthesis, and engineering readiness
- bootstrap scripts to create a manifest, scaffold an Obsidian vault, and generate the first audit and readiness report
- starter prompts you can paste into Codex to run the workflow end to end
- templates and examples so you can test the approach without any product-specific customization

This package is intentionally generic. It does not assume Influitive, any specific repository, or any specific support system.

## Who this is for

Use this if you want to test whether the approach works on your own product, service, platform, or repository set.

Typical use cases:
- product teams that want a second brain for docs, support, and engineering context
- engineering teams that want code intelligence, bug workflows, and readiness reporting
- operators who want a repeatable way to onboard many products into the same methodology

## Maintainers

- Colin Guilfoyle
- Sergio Wermuth

## What you need

- Codex desktop or Codex CLI with access to local skills
- Python 3
- Git
- Obsidian
- optional: GitHub CLI (`gh`) if you want repo-mirror sync to resolve default branches automatically

## Fastest path

1. Read [QUICKSTART.md](QUICKSTART.md).
2. Run `scripts/install_codex_starter.sh`.
3. Run `scripts/bootstrap_test_workspace.sh` with your product name, slug, vault path, and workspace path.
4. Copy your local repositories and source material into the workspace paths described in the generated manifest.
5. Use the prompts in `prompts/` inside Codex.

## Package layout

- `skills/`
  - portable copies of the generic skills
- `scripts/`
  - install, bootstrap, and verification helpers
- `prompts/`
  - ready-to-paste Codex prompts for each phase
- `templates/`
  - manifest and automation templates
- `examples/`
  - a sample manifest and test setup notes

## Core workflow

1. Install the skills into your Codex home.
2. Bootstrap a manifest-driven workspace for your product.
3. Scaffold the Obsidian vault.
4. Add source material and repositories.
5. Use Codex to ingest, synthesize, and connect the information.
6. Generate the engineering-readiness report.
7. Optionally add recurring automations after the first manual pass is proven.

## Recommended first test

Pick one real codebase and one small source corpus:
- 1 to 3 repositories
- 5 to 20 product or support documents
- one Obsidian vault path

Do not start with your largest product first. The goal of the first run is to prove the workflow, not to ingest everything.

## Next reads

- [QUICKSTART.md](QUICKSTART.md)
- [INSTALL.md](INSTALL.md)
- [WORKFLOW.md](WORKFLOW.md)
- [TEST-ON-YOUR-CODEBASE.md](TEST-ON-YOUR-CODEBASE.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [MAINTAINERS.md](MAINTAINERS.md)
