from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = TOOLS_DIR / "rebuild_product_brain.py"


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NoteEnrichmentTests(unittest.TestCase):
    def test_product_ontology_exposes_cited_machine_readable_strategy(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_ontology_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": []},
            },
            {
                "capabilities": [
                    {
                        "key": "advocacy",
                        "title": "Customer Advocacy",
                        "description": "Customer advocacy workflows.",
                        "keywords": ["advocacy", "campaign"],
                        "repos": ["acme-app"],
                    }
                ]
            },
        )
        support_record = {
            "item": {
                "title": "Acme Product Overview",
                "source_url": "https://support.example.com/article/100",
                "relative_path": "100-overview.md",
            },
            "text": "Acme helps customer advocates run campaigns and rewards.",
            "signals": {
                "title": "Acme Product Overview",
                "headings": ["Overview"],
                "bullets": ["Admins create advocacy campaigns for members."],
                "paragraphs": ["Acme helps customer advocates run campaigns and rewards."],
            },
            "source_ref": "100-overview.md",
        }

        ontology = module.build_product_ontology(
            manifest={"product": {"name": "Acme", "slug": "acme"}},
            support_records=[support_record],
            wiki_records=[],
            repo_snapshots=[
                {
                    "name": "acme-app",
                    "role": "primary",
                    "branch": "main",
                    "readme_title": "Acme",
                    "readme_summary": "Acme is a customer advocacy platform.",
                    "top_dirs": ["src"],
                    "key_files": ["package.json"],
                    "monorepo_services": ["api"],
                    "monorepo_apps": ["web"],
                }
            ],
            capability_rows=[
                {
                    "title": "Customer Advocacy",
                    "link": "[[Customer Advocacy]]",
                    "support_count": 1,
                    "wiki_count": 0,
                    "repos": ["acme-app"],
                    "code_count": 2,
                }
            ],
            code_intel={
                "summary": {"route_count": 1, "schema_count": 1, "test_anchor_count": 1},
                "repos": [{"repo": "acme-app", "test_anchor_count": 1}],
                "files": [
                    {
                        "repo": "acme-app",
                        "relative_path": "src/api/campaigns.ts",
                        "dependencies": [],
                    }
                ],
                "graph": {
                    "routes": [{"from": "acme-app/src/api/campaigns.ts", "to": "GET /campaigns"}],
                    "schemas": [{"from": "acme-app/src/api/campaigns.ts", "to": "type:Campaign"}],
                    "tests": [{"from": "acme-app/src/api/campaigns.test.ts", "to": "campaign test"}],
                },
            },
            external_links=[],
            docx_extracts=[],
        )

        self.assertEqual(ontology["source"], "codex-second-brain-starter-kit")
        self.assertEqual(ontology["product"]["slug"], "acme")
        self.assertIn("customer advocates", ontology["product_purpose"])
        self.assertIn("Customer Advocacy", ontology["capabilities"])
        self.assertIn("GET /campaigns", ontology["apis"])
        self.assertIn("type:Campaign", ontology["data_entities"])
        self.assertIn("campaign test", ontology["test_map"])
        self.assertEqual(ontology["fields"]["product_purpose"]["confidence"], "medium")
        self.assertEqual(ontology["fields"]["product_purpose"]["citations"][0]["source_type"], "support")

    def test_support_note_preserves_full_article_content_and_obsidian_links(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_note_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": []},
            },
            {
                "capabilities": [
                    {
                        "key": "platform-core",
                        "title": "Platform Core",
                        "description": "Core product behavior.",
                        "keywords": ["platform"],
                        "repos": ["core-repo"],
                    }
                ]
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_path = Path(tmp_dir) / "100-article.md"
            raw_path.write_text(
                "\n".join(
                    [
                        "# Sample Article",
                        "",
                        "*Source:* https://support.example.com/article/100",
                        "",
                        "---",
                        "",
                        "# Sample Article",
                        "",
                        "## Overview",
                        "",
                        "Read [Related Article](https://support.example.com/article/2000) for more detail.",
                        "",
                        "This article also references Article 2000 in plain text.",
                        "",
                        "## Solution",
                        "",
                        "- First step",
                        "- Second step",
                    ]
                )
            )

            body = module.build_support_note(
                item={
                    "title": "Sample Article",
                    "source_url": "https://support.example.com/article/100",
                    "article_id": "100",
                    "category": "support-article",
                    "relative_path": "support/100-article.md",
                },
                raw_path=raw_path,
                stem="Support - 100 - Sample Article",
                capabilities=["platform-core"],
                repo_links=["[[Repo - core-repo]]"],
                link_records=[],
                article_note_stems={"2000": "Support - 2000 - Related Article"},
                wiki_note_stems={"How-to/Guide.md": "Wiki - How-to - Guide"},
                related_support_links=[],
                related_wiki_links=["[[Wiki - How-to - Guide]]"],
                code_reference_links=[],
                conflicts=[],
            )

        self.assertIn("## Full Article Content", body)
        self.assertIn("[[Support - 2000 - Related Article|Related Article]]", body)
        self.assertIn("[[Support - 2000 - Related Article|Article 2000]]", body)
        self.assertIn("## Related support notes", body)

    def test_support_note_includes_code_references_and_conflicts(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_conflict_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": ["legacy.example.com"]},
            },
            {
                "capabilities": [
                    {
                        "key": "platform-core",
                        "title": "Platform Core",
                        "description": "Core product behavior.",
                        "keywords": ["platform"],
                        "repos": ["core-repo"],
                    }
                ]
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_path = Path(tmp_dir) / "300-article.md"
            raw_path.write_text("# Sample Article\n\nThis explains platform behavior.")

            body = module.build_support_note(
                item={
                    "title": "Sample Article",
                    "source_url": "https://support.example.com/article/300",
                    "article_id": "300",
                    "category": "support-article",
                    "relative_path": "support/300-article.md",
                },
                raw_path=raw_path,
                stem="Support - 300 - Sample Article",
                capabilities=["platform-core"],
                repo_links=["[[Repo - core-repo]]"],
                link_records=[
                    {
                        "url": "https://legacy.example.com/old-page",
                        "domain": "legacy.example.com",
                        "status": "stale-doc-reference",
                    },
                    {
                        "url": "https://docs.example.com/private-page",
                        "domain": "docs.example.com",
                        "status": "blocked",
                        "http_status": 403,
                        "error": "Forbidden",
                    },
                ],
                article_note_stems={},
                wiki_note_stems={},
                related_support_links=[],
                related_wiki_links=[],
                code_reference_links=[
                    "[[Code Ref - core-repo - services -- platform.rb]]",
                ],
                conflicts=[
                    "Documentation drift: this note still points to a legacy internal documentation host.",
                ],
            )

        self.assertIn("## Source code references", body)
        self.assertIn("[[Code Ref - core-repo - services -- platform.rb]]", body)
        self.assertIn("## Conflicts and mismatches", body)
        self.assertIn("Documentation drift:", body)
        self.assertIn("## Uncaptured evidence", body)
        self.assertIn("[blocked] [https://docs.example.com/private-page](https://docs.example.com/private-page)", body)

    def test_code_reference_note_includes_engineering_summary_and_risk_signals(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_code_reference_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": ["legacy.example.com"]},
            },
            {
                "capabilities": [
                    {
                        "key": "marketo-integration",
                        "title": "Marketo Integration",
                        "description": "Marketo connectivity and lead sync behavior.",
                        "keywords": ["marketo", "lead sync"],
                        "repos": ["integrations-repo"],
                    }
                ]
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            code_path = Path(tmp_dir) / "marketo.js"
            code_path.write_text(
                "\n".join(
                    [
                        "// Push referral leads to Marketo and map the payload.",
                        "class MarketoClient {",
                        "  syncLead(payload) {",
                        "    return payload;",
                        "  }",
                        "}",
                        "",
                        "export async function pushLead(lead) {",
                        "  try {",
                        "    console.log(lead.email);",
                        "    return new MarketoClient().syncLead(lead);",
                        "  } catch (error) {",
                        "    return null;",
                        "  }",
                        "}",
                        "",
                        "// TODO: remove debug logging once the connector is stable.",
                    ]
                )
            )

            body = module.build_code_reference_note(
                hit={
                    "repo": "integrations-repo",
                    "absolute_path": str(code_path),
                    "relative_path": "connectors/marketo.js",
                    "line_number": 8,
                    "score": 7,
                    "sample": "export async function pushLead(lead) {",
                },
                support_links=["[[Support - 100 - Marketo Lead Sync]]"],
                wiki_links=["[[Wiki - How-to - Marketo Setup]]"],
                capability_links=["[[Capability - Marketo Integration]]"],
                code_file={
                    "language": "JavaScript",
                    "parse_quality": "complete",
                    "symbols": {"classes": ["MarketoClient"], "functions": ["pushLead"], "types": []},
                    "symbol_count": 2,
                    "routes": [{"method": "POST", "path": "/marketo/leads", "source": "connectors/marketo.js"}],
                    "route_count": 1,
                    "schemas": [{"kind": "type", "name": "LeadPayload", "source": "connectors/marketo.js"}],
                    "schema_count": 1,
                    "tests": [{"kind": "js-test", "name": "pushes leads", "source": "connectors/marketo.test.js"}],
                    "test_anchor_count": 1,
                    "dependencies": ["axios"],
                    "dependency_count": 1,
                    "imports": ["axios"],
                    "calls": ["syncLead"],
                    "env_vars": ["MARKETO_TOKEN"],
                    "migrations": [],
                    "churn_score": 3,
                    "owner_candidates": ["Ada"],
                    "parser_errors": [],
                },
            )

        self.assertIn("## Class and module summary", body)
        self.assertIn("symbol_count: 2", body)
        self.assertIn("route_count: 1", body)
        self.assertIn("schema_count: 1", body)
        self.assertIn("test_anchor_count: 1", body)
        self.assertIn("dependency_count: 1", body)
        self.assertIn("churn_score: 3", body)
        self.assertIn("owner_candidates:", body)
        self.assertIn("parse_quality: \"complete\"", body)
        self.assertIn("MarketoClient", body)
        self.assertIn("pushLead", body)
        self.assertIn("## Route and API surfaces", body)
        self.assertIn("POST /marketo/leads", body)
        self.assertIn("## Schema and data contracts", body)
        self.assertIn("LeadPayload", body)
        self.assertIn("## Test anchors", body)
        self.assertIn("pushes leads", body)
        self.assertIn("## Dependencies", body)
        self.assertIn("axios", body)
        self.assertIn("## Ownership and churn", body)
        self.assertIn("Ada", body)
        self.assertIn("## Parser limitations", body)
        self.assertIn("## Intentions and behavior", body)
        self.assertIn("Push referral leads to Marketo", body)
        self.assertIn("## Relevance", body)
        self.assertIn("Support notes: `1`", body)
        self.assertIn("Wiki notes: `1`", body)
        self.assertIn("## Detected bugs and risks", body)
        self.assertIn("TODO/FIXME", body)
        self.assertIn("console logging", body)
        self.assertIn("error handling", body)

    def test_code_reference_note_flags_legacy_or_drift_conflicts(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_code_conflict_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": ["legacy.example.com"]},
            },
            {
                "capabilities": [
                    {
                        "key": "platform-core",
                        "title": "Platform Core",
                        "description": "Core platform behavior.",
                        "keywords": ["platform"],
                        "repos": ["core-repo"],
                    }
                ]
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            code_path = Path(tmp_dir) / ".gitlab-ci.yml"
            code_path.write_text(
                "\n".join(
                    [
                        "deploy:",
                        "  script:",
                        "    - curl https://legacy.example.com/builds/internal",
                    ]
                )
            )

            body = module.build_code_reference_note(
                hit={
                    "repo": "core-repo",
                    "absolute_path": str(code_path),
                    "relative_path": "devops/.gitlab-ci.yml",
                    "line_number": 1,
                    "score": 3,
                    "sample": "deploy:",
                },
                support_links=[],
                wiki_links=[],
                capability_links=["[[Capability - Platform Core]]"],
            )

        self.assertIn("## Conflicts and mismatches", body)
        self.assertIn("legacy GitLab", body)
        self.assertIn("historical or drift-prone", body)


if __name__ == "__main__":
    unittest.main()
