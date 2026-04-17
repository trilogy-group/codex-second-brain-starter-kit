# Contributing

Thanks for contributing to the Codex Second Brain Starter Kit.

## What this project is for

This project exists to help teams test and adopt a generic second-brain workflow for product, documentation, support, and engineering work across their own codebases.

The goal is to keep the package:
- generic
- reproducible
- manifest-driven
- useful for both a first proof run and future scale-out

## Contribution principles

- keep reusable logic in the generic skills and scripts
- avoid product-specific assumptions unless they belong in examples
- prefer manifest and template changes over one-off workflow forks
- keep docs practical and operator-focused

## What to update when you change the system

If you change behavior, update the relevant parts of the package:
- `README.md`
- `QUICKSTART.md`
- `WORKFLOW.md`
- prompts in `prompts/`
- templates in `templates/`
- skill references if the operating model changed

## Typical contribution flow

1. Create a focused branch.
2. Keep changes scoped.
3. Update docs when behavior changes.
4. Run the install and bootstrap flow on a temporary workspace.
5. Verify the generated vault audit and readiness report still work.

## Good pull requests include

- what changed
- why it changed
- whether it affects the generic workflow, the templates, or only examples
- how it was validated
