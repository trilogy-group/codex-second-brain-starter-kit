# Standard Automation Pack Template

Use this when asking Codex to create the recurring automation layer.

## Required automations

1. Source-truth sync
- Purpose: refresh the vault when the underlying skill or source-of-truth files change
- Default cadence: hourly

2. PR merge sync
- Purpose: refresh the vault when tracked pull requests merge
- Default cadence: hourly

3. Repo mirror sync
- Purpose: refresh safe repo mirrors without touching active worktrees
- Default cadence: hourly

4. Engineering-readiness audit
- Purpose: keep the gap report current
- Default cadence: weekly

## Rule

The automation pack should stay consistent across products. Product-specific differences should live in the manifest and prompt parameters.
