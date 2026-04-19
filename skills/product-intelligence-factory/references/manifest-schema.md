# Product Manifest Schema

## Required Top-Level Keys

- `product`
- `sources`
- `profile`
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
  support_article_url_template: https://support.example.com/article/{article_id}
  stale_doc_hosts:
    - legacy.example.com

profile:
  intelligence_path: /absolute/path/to/workspace/config/intelligence-profile.yaml

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
      title: Source coverage and provenance
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
- `ask: 2` through `ask: 8` can be used to break engineering readiness into distinct operational categories such as linked-page capture, code intelligence, runtime understanding, traceability, runbooks, blockers, and automation opportunities.
- Keep evidence entries as absolute paths or URLs when possible.
- `profile.intelligence_path` should point to a capability profile that stays generic at the tooling layer but is allowed to carry product-specific keywords and repo mappings.
- Leave `sources.support_article_url_template` empty if the source system does not have a stable article URL pattern.
