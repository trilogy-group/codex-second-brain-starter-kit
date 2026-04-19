# Codex Second Brain Starter Kit

This is a generic Codex setup for testing the second-brain workflow on any codebase.

## Video overview

This intro explains the concept behind the repository:

[![Watch the intro overview](assets/video-overview.gif)](https://share.synthesia.io/52d11cfd-a0e6-4fca-ba51-3bdf2097c587)

[Watch the intro now!](https://share.synthesia.io/52d11cfd-a0e6-4fca-ba51-3bdf2097c587)

It packages:
- reusable Codex skills for product intelligence, Obsidian synthesis, and engineering readiness
- a portfolio wizard that can initialize and manage multiple second brains
- bootstrap scripts to create a manifest, scaffold an Obsidian vault, and generate the first audit and readiness report
- packaged source-index, vault-rebuild, and privacy-sanitizing scripts for richer second-brain generation
- starter prompts you can paste into Codex to run the workflow end to end
- templates and examples so you can test the approach without any product-specific customization

This package is intentionally generic. It does not assume any specific repository, product, or support system.

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

- Codex desktop or Codex CLI with access to local skills and these installed plugins: `Computer Use`, `GitHub`, `Gmail`, `Google Calendar`, `Google Drive`, `Life Science Research`, `Superpowers`
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
  - install, wizard, bootstrap, verification, and manifest/bootstrap helpers
- `prompts/`
  - ready-to-paste Codex prompts for each phase
- `templates/`
  - manifest, profile, and automation templates
- `examples/`
  - a sample manifest, sample intelligence profile, and test setup notes

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

## Sample prompt: product second brain

This version is meant to be paste-ready from a fresh Codex session. It tells Codex to start from the starter-kit repository itself, bootstrap what is missing, and ask only the questions that are actually needed to continue.

```md
Using https://github.com/trilogy-group/codex-second-brain-starter-kit, prepare my second brain for my product.

Start by reading that repository and following its recommended workflow. If you need to clone it, set it up, create a manifest, or scaffold a workspace or vault, do that as part of the job instead of asking me to do it first.

Create and fill the product manifest yourself. Infer as much as you can from the repository list, the attached documentation, and any source material you discover while following the workflow. Only ask me for manifest values if a missing path, access requirement, or product decision would materially change the result.

If plan mode is available, use it.

Ask me only the questions that are necessary to keep going. In particular, ask only if you are blocked by a missing path, missing access, or a decision that would materially change the output.

These are the repositories that must be covered:
- "trilogy-group/influitive-advocatehub-Wiki",
- "trilogy-group/influitive-advocatehub-influitive",
- "trilogy-group/influitive-advocatehub-integrations-customers",
- "trilogy-group/influitive-advocatehub-integrations-authenticator",
- "trilogy-group/influitive-advocatehub-integrations-middleware",
- "trilogy-group/influitive-advocatehub-ios-whitelabel"

For the code repositories, I want a full code-intelligence layer in the Obsidian second brain, not just repo summaries.

Please traverse every repository deeply and extract all important engineering data from the code itself, including architecture, implementation details, feature mappings, bugs, risks, code quality signals, runtime behavior, and operational context.

Requirements for the code-intelligence layer:

- Preserve raw-source provenance before summarizing anything.
- Record repo origin, branch, commit SHA, local path, main entrypoints.
- Create repo catalog notes for every repository with purpose, business role, tech stack, runtime surfaces, deploy surfaces, key directories, important files, and representative code paths.
- Create architecture and service-map notes that explain services, apps, packages, modules, APIs, queues, jobs, workers, databases, event flows, and dependencies between repos and systems.
- Create rich code-reference notes for important files, packages, modules, classes, interfaces, methods, functions, jobs, routes, schemas, migrations, and tests.
- For each code-reference note, capture:
  - what it does
  - why it exists
  - implementation intent
  - inputs and outputs
  - dependencies and dependents
  - interfaces it implements or exposes
  - related routes, events, tables, schemas, configs, feature flags, and tests
  - side effects, state changes, and external integrations
  - static risk signals
  - known conflicts, ambiguity, or stale assumptions
- Map product features and support topics to code.
- For every important capability, build links from feature -> repo -> file -> class/interface -> method/function -> test -> runbook/config where possible.
- Build support-to-code traceability notes that connect support articles, bug reports, wiki pages, and operational docs to the exact implementation anchors in code.
- Extract data-model intelligence:
  - domain entities
  - tables and migrations
  - DTOs, schemas, protobuf/graphql/openapi contracts
  - events, messages, topics, queues, webhooks
  - producers and consumers
  - data lineage between systems when visible in code
- Extract runtime and operational intelligence:
  - env vars
  - configuration files
  - background jobs
  - schedulers and cron flows
  - deployment config
  - CI/CD workflows
  - infra code
  - observability/logging hooks
  - auth/authz boundaries
  - caching layers
  - rate limiting
  - retries
  - failure handling
- Extract test intelligence:
  - unit/integration/e2e test structure
  - important fixtures and factories
  - untested critical paths
  - flaky-looking areas
  - gaps between implementation and tests
  - tests that anchor high-risk features
- Extract bug and risk intelligence, including:
  - TODO/FIXME/HACK markers
  - dead or orphaned code
  - duplicated logic
  - large or overly central files
  - weak error handling
  - missing validation
  - suspicious nil/null handling
  - race conditions or async hazards
  - performance hotspots
  - security/privacy risks
  - migration risks
  - brittle feature-flag logic
  - stale compatibility layers
  - places where docs and code disagree
- If git history is available, include hotspots such as:
  - high-churn files
  - bug-prone areas
  - ownership concentration
  - recent risky edits
  - modules with large blast radius
- Explicitly identify probable bug candidates and quality concerns, with evidence and code references, not just generic warnings.
- Create notes for cross-repo relationships:
  - shared libraries
  - duplicated contracts
  - API consumers/providers
  - frontend/backend pairings
  - service boundaries
  - integration seams
  - migration paths
  - legacy vs current implementations
- Where code is inaccessible, missing, generated, vendored, or blocked, record that explicitly instead of silently skipping it.
- Keep raw extracts separate from synthesized notes.
- Use Obsidian wikilinks throughout.
- Ensure every note has YAML frontmatter and at least one meaningful wikilink.
- Build or update the following vault notes as needed:
  - repo catalog
  - code reference index
  - architecture and service map
  - feature-to-code map
  - support-to-code traceability map
  - bug candidate log
  - code quality watchlist
  - runtime and deployment map
  - data model map
  - test coverage and testing gaps note
  - blocked code access note
  - conflicts and stale documentation note
- Do not stop at file names or directory trees. I want implementation-level understanding rich enough that an engineer could use the vault to debug, extend, review, or hand off the product safely.


Additional source material:
- I am attaching support article files and other documentation in this thread.
- Traverse every attached file and every reachable link referenced inside those files.
- If there are video files, transcribe them using Whisper and use them as source material.
- Follow links found in the support docs, wiki pages, and related captured pages when they add useful product, support, engineering, or operational context.
- If a page is restricted, redirected, deleted, timed out, or otherwise inaccessible, record that explicitly instead of silently skipping it.

I want the result to be a real Obsidian second brain, not a flat summary dump. Please:
- preserve raw-source provenance before summarizing anything
- run the packaged source-index build and vault rebuild scripts when they are available
- extract useful content from support articles, repo documentation, wiki pages, and reachable external references
- if any page requires authentication, open a new browser session and ask me to authenticate with my data, store the authentication details for next iterations
- create notes using Obsidian wikilinks throughout
- create the references in Obsidian syntax
- keep raw extracts separate from synthesized notes
- build or update the key index notes, source maps, repo catalog notes, architecture notes, support-to-code traceability notes, and blocked-access notes that are needed
- connect documentation claims to the relevant repos, services, apps, and files
- make code-reference notes rich enough to include class or module summaries, implementation intent, relevance, static risk signals, and conflict notes
- flag conflicts, stale documentation, and unresolved assumptions when docs, support content, and code do not agree
- continue traversing the reachable high-value source graph until the important material is covered

Finish with:
- a concise summary of what was ingested, what was blocked, and what still needs manual access
- a vault audit written into the vault
- the next highest-leverage follow-ups to improve completeness, traceability, and automation
```
