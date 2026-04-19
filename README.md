# Codex Second Brain Starter Kit

This is a generic Codex setup for testing the second-brain workflow on any codebase.

## Video overview

This demo explains the concept behind the repository:

[![Watch the video overview](https://69jr5v75rc.execute-api.eu-west-1.amazonaws.com/prod/52d11cfd-a0e6-4fca-ba51-3bdf2097c587/thumbnail.jpg)](https://share.synthesia.io/52d11cfd-a0e6-4fca-ba51-3bdf2097c587)

[Watch the demo now!](https://share.synthesia.io/52d11cfd-a0e6-4fca-ba51-3bdf2097c587)

It packages:
- reusable Codex skills for product intelligence, Obsidian synthesis, and engineering readiness
- a portfolio wizard that can initialize and manage multiple second brains
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
3. Use `scripts/second_brain_wizard.py` to initialize a portfolio and add your first second brain.
4. Copy your local repositories and source material into the workspace paths described in the generated manifest.
5. Use the prompts in `prompts/` inside Codex.

## Package layout

- `skills/`
  - portable copies of the generic skills
- `scripts/`
  - install, wizard, bootstrap, and verification helpers
- `prompts/`
  - ready-to-paste Codex prompts for each phase
- `templates/`
  - manifest and automation templates
- `examples/`
  - a sample manifest and test setup notes

## Core workflow

1. Install the skills into your Codex home.
2. Initialize a portfolio root for one or many second brains.
3. Add a new second brain into that portfolio.
4. Add source material and repositories.
5. Use Codex to ingest, synthesize, and connect the information.
6. Generate or refresh the engineering-readiness report.
7. Optionally add recurring automations after the first manual pass is proven.

## Next reads

- [QUICKSTART.md](QUICKSTART.md)
- [INSTALL.md](INSTALL.md)
- [WORKFLOW.md](WORKFLOW.md)
- [WIZARD.md](WIZARD.md)
- [TEST-ON-YOUR-CODEBASE.md](TEST-ON-YOUR-CODEBASE.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [MAINTAINERS.md](MAINTAINERS.md)
