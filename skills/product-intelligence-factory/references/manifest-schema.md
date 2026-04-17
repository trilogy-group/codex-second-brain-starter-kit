# Product Manifest Schema

## Required Top-Level Keys

- `product`
- `sources`
- `repositories`
- `automation_pack`
- `engineering_readiness`

## Recommended Shape

```yaml
product:
  name: Example Product
  slug: example-product
  mode: hybrid
  vault_path: /absolute/path/to/vault
  workspace_path: /absolute/path/to/workspace

sources:
  corpus_path: /absolute/path/to/source-corpus
  mirror_path: /absolute/path/to/workspace/_source_extract/product
  docx_extract_path: /absolute/path/to/workspace/_source_extract/docx_text
  auth_cache_path: /absolute/path/to/workspace/_auth_cache.json
  support_login: browser-session

repositories:
  local_clone_root: /absolute/path/to/workspace/_repos
  safe_mirror_root: /absolute/path/to/workspace/_repo_mirrors
  items:
    - owner: org
      name: repo-name
      role: core-app
      default_branch: main
      local_path: /absolute/path/to/workspace/_repos/repo-name
      url: https://github.com/org/repo-name

automation_pack:
  source_truth_sync:
    automation_id: example-source-truth-sync
    status: active
  pr_merge_sync:
    automation_id: example-pr-merge-sync
    status: active
  repo_mirror_sync:
    automation_id: example-repo-mirror-sync
    status: active
  readiness_audit:
    automation_id: example-engineering-readiness
    status: active

engineering_readiness:
  categories:
    - key: reusable-import-factory
      title: Reusable product import factory
      ask: 1
      status: partial
      summary: One-line status summary.
      evidence:
        - /absolute/path/to/evidence
      missing:
        - Missing capability
      next_steps:
        - Concrete next step
```

## Status Values

- `done`
- `partial`
- `missing`

## Notes

- `ask: 1` maps to the manager ask about importing any product into the system.
- `ask: 2` maps to the manager ask about making the product engineering-ready for feature work, bugs, CI/CD, deployment, and infra support.
- Keep evidence entries as absolute paths or URLs when possible.
