# Product Automation Pack

## Core Automations

### 1. Source-Truth Sync

Purpose:
- Refresh the product vault when the underlying skill or workflow source of truth changes.

Cadence:
- hourly

### 2. PR Merge Sync

Purpose:
- Refresh the product vault when tracked GitHub pull requests merge.

Cadence:
- hourly

### 3. Repo Mirror Sync

Purpose:
- Update safe read-only or disposable repo mirrors without touching active worktrees.

Cadence:
- hourly

### 4. Engineering Readiness Audit

Purpose:
- Recompute the product's engineering-readiness gap report and highlight what still blocks scale.

Cadence:
- weekly

## Implementation Rule

The automation pack should be consistent across products. Product-specific differences should live in the manifest and automation prompt parameters, not in ad hoc automation design.
