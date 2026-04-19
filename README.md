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

## Sample prompt: Influitive second brain

If you already initialized a manifest and staged the repositories plus source files, this is a stronger paste-ready Codex prompt for the Influitive use case. Attach the support article files and any other Influitive docs to the Codex thread before sending it.

```md
Use `product-intelligence-factory`, `obsidian-intelligence-system`, and `product-engineering-ops`.

Run in plan mode.

Using this starter kit, prepare my second brain for Influitive.

Use this manifest:
`/absolute/path/to/second-brain-portfolio/manifests/product.yaml`

The product is Influitive. These repositories must be covered:
- `influitive-advocatehub-Wiki`
- `influitive-advocatehub-influitive`
- `influitive-advocatehub-integrations-customers`
- `influitive-advocatehub-integrations-authenticator`
- `influitive-advocatehub-integrations-middleware`
- `influitive-advocatehub-ios-whitelabel`

Additional source material:
- I am attaching Influitive support article files and other documentation in this thread.
- Use the manifest's `corpus_path`, `mirror_path`, and `docx_extract_path` as the source boundaries.
- Traverse every attached file and every reachable link referenced inside those files.
- Traverse links found in the engineering wiki, support docs, and captured pages when they add real product or operational context.
- If a page is restricted, redirected, deleted, timed out, or otherwise inaccessible, record that explicitly in the vault instead of silently skipping it.

Build the second brain as a linked Obsidian knowledge system, not as a flat summary dump.

Requirements:
- preserve raw-source provenance before summarizing anything
- extract usable content from support articles, repo documentation, wiki pages, and reachable external references
- create Obsidian notes with YAML frontmatter and at least one wikilink per note
- use Obsidian wikilinks consistently for products, features, services, integrations, runbooks, support themes, and repositories
- keep raw extracts separate from synthesized notes
- create or update home notes, source indexes, repo catalog notes, architecture maps, support-to-code traceability notes, and blocked-access notes where needed
- connect documentation claims to the relevant repos, services, apps, and files
- flag conflicts, stale documentation, and unresolved assumptions when docs, support content, and code do not agree
- keep the workflow manifest-driven and generic rather than creating Influitive-specific one-off logic

Working style:
- continue traversing discovered links until the reachable high-value source graph is covered
- prefer one durable note per concept, workflow, feature, service, decision, or problem
- ask questions only if blocked by missing access or ambiguity that would materially change the output

Finish with:
- a concise summary of what was ingested, what was blocked, and what still needs manual access
- a vault audit written into the vault
- the next highest-leverage follow-ups to improve completeness, traceability, and automation
```
