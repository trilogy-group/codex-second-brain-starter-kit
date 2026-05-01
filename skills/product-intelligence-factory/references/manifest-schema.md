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

# The profile file should include:
# semantic_clustering:
#   provider: openai
#   embedding_model: text-embedding-3-small
#   min_cluster_size: 3
#   similarity_threshold: 0.78
#   max_clusters: 40
# code_intelligence:
#   max_files_per_repo: 1200
#   include_git_history: true
#   include_tests: true
#   include_dependency_graph: true

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
- `ask: 2` and later can be used to break readiness into distinct operational categories such as linked-page capture, code intelligence, Product BASB alignment, progressive summarization, runtime understanding, traceability, runbooks, blockers, output conversion, archive hygiene, and automation opportunities.
- Keep evidence entries as absolute paths or URLs when possible.
- `profile.intelligence_path` should point to a capability profile that stays generic at the tooling layer but is allowed to carry product-specific keywords and repo mappings.
- Semantic intermediate packets require OpenAI embeddings during rebuild. Set `OPENAI_API_KEY` in the runtime environment before running `rebuild_product_brain.py`; the generated cache is stored under `sources.mirror_path/inventories/embedding_cache.json`.
- Leave `sources.support_article_url_template` empty if the source system does not have a stable article URL pattern.
