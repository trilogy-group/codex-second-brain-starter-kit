# Wizard Guide

The starter kit now includes a portfolio wizard for managing multiple second brains.

Main script:

```bash
./scripts/second_brain_wizard.py
```

You can use it interactively with no arguments, or non-interactively with subcommands.

## Portfolio model

The wizard manages a portfolio root containing:

- `second-brains.yaml`
- `workspaces/`
- `manifests/`
- `vaults/` unless you point it at an external Obsidian root

Each second brain still has its own:
- manifest
- workspace
- vault
- audit note
- readiness report

## Commands

### Initialize a portfolio

```bash
./scripts/second_brain_wizard.py init-portfolio \
  --portfolio-root "/absolute/path/to/second-brain-portfolio" \
  --name "Acme Product Portfolio" \
  --obsidian-root "/absolute/path/to/Obsidian/Product Brains"
```

### Add a second brain

```bash
./scripts/second_brain_wizard.py add-brain \
  --portfolio-root "/absolute/path/to/second-brain-portfolio" \
  --name "Acme Platform" \
  --slug "acme-platform" \
  --mode hybrid
```

### List all second brains

```bash
./scripts/second_brain_wizard.py list-brains \
  --portfolio-root "/absolute/path/to/second-brain-portfolio"
```

### Run a portfolio doctor check

```bash
./scripts/second_brain_wizard.py doctor \
  --portfolio-root "/absolute/path/to/second-brain-portfolio"
```

### Refresh audits and readiness reports

```bash
./scripts/second_brain_wizard.py refresh \
  --portfolio-root "/absolute/path/to/second-brain-portfolio"
```

Optionally target a single second brain:

```bash
./scripts/second_brain_wizard.py refresh \
  --portfolio-root "/absolute/path/to/second-brain-portfolio" \
  --slug "acme-platform"
```

## Interactive mode

If you run the script without a subcommand, it opens a simple menu for:
- creating a portfolio
- adding a second brain
- listing second brains
- running doctor checks
- refreshing outputs

## Why this matters

The wizard is the portfolio-level startup path. It lets one installation support many second brains without making users handcraft a new workspace every time.
