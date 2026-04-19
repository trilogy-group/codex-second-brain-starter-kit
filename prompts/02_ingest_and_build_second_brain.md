# Prompt 02: Ingest And Build The Second Brain

Use `product-intelligence-factory` and `obsidian-intelligence-system`.

Build the product second brain from the sources defined in this manifest:
`/absolute/path/to/product.yaml`

Requirements:
- run the packaged source-index build and rebuild scripts when they are available for this manifest
- preserve raw sources before summarizing them
- build linked notes instead of a dump
- preserve full support and wiki content inside the generated notes, not just summaries
- create home notes, research hubs, and product-memory notes
- connect documentation, external links, and repository context where relevant
- create rich code-reference notes that explain class or module summaries, implementation intent, relevance, static risk signals, and conflicts
- add conflicts whenever documentation and code disagree
- show exact uncaptured or blocked URLs instead of only reporting counts
- sanitize generated vault notes for obvious PII and credential leakage
- finish with a vault audit written into the vault
