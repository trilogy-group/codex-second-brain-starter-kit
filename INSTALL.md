# Install Guide

## Goal

Install the bundled generic skills into Codex so they can be invoked by name:
- `obsidian-intelligence-system`
- `product-intelligence-factory`
- `product-engineering-ops`

## Install command

```bash
cd /absolute/path/to/codex-second-brain-starter-kit
./scripts/install_codex_starter.sh
```

## Where the skills go

The install script copies them to:

```bash
${CODEX_HOME:-$HOME/.codex}/skills
```

## Verify the install

```bash
./scripts/verify_setup.sh
```

You should see:
- the three skill directories present
- Python available
- the bundled scripts callable

## Reinstall behavior

The script replaces the installed copies of these three skills with the versions packaged here. That makes the kit reproducible, but if you have your own local edits to those same skills, back them up first.
