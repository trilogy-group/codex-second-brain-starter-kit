# Prompt 02: Ingest And Build The Second Brain

Use `product-intelligence-factory` and `obsidian-intelligence-system`.

Build the product second brain from the sources defined in this manifest:
`/absolute/path/to/product.yaml`

Requirements:
- run the packaged source-index build and rebuild scripts when they are available for this manifest
- ensure `OPENAI_API_KEY` is available before rebuild so semantic clustering can run; fail clearly if it is missing
- preserve raw sources before summarizing them
- run CODE in order: capture source evidence, organize it into the manifest/PARA structure, distill it into durable notes, and express high-value findings into output candidates
- build linked notes instead of a dump
- preserve full support and wiki content inside the generated notes, not just summaries
- add Product BASB frontmatter to durable generated notes: `basb_stage`, `para_category`, `distillation_level`, `actionability`, and optional `output_target`
- include Essence and Use in current project sections before raw source content
- create intermediate packets when a reusable support, wiki, code, or planning cluster can feed more than one future initiative
- create or update vault-native output candidates for PRDs, specs, tickets, PR plans, runbooks, decisions, launch notes, and post-launch learnings when the evidence supports them
- generate weekly review and stale-source archive candidate notes after rebuild; do not create live delivery-system tickets unless explicitly asked
- create home notes, research hubs, and product-memory notes
- connect documentation, external links, and repository context where relevant
- create rich code-reference notes and code-intelligence maps for symbols, routes, schemas, calls, dependencies, tests, ownership/churn, parser limitations, implementation intent, static risk signals, and conflicts
- generate semantic intermediate packets from OpenAI embeddings over compact evidence cards, preserving links back to source evidence and related code surfaces
- add conflicts whenever documentation and code disagree
- show exact uncaptured or blocked URLs instead of only reporting counts
- record access requirements and use approved credential/session storage for authenticated sources; never store raw credentials in the vault
- sanitize generated vault notes for obvious PII and credential leakage
- finish with a vault audit written into the vault
