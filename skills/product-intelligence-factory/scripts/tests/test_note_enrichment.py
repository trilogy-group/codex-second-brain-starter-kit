from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

        old_fixture = os.environ.get("PRODUCT_BASB_BUSINESS_VALUE_FIXTURE")
        os.environ["PRODUCT_BASB_BUSINESS_VALUE_FIXTURE"] = "1"
        try:
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
        finally:
            if old_fixture is None:
                os.environ.pop("PRODUCT_BASB_BUSINESS_VALUE_FIXTURE", None)
            else:
                os.environ["PRODUCT_BASB_BUSINESS_VALUE_FIXTURE"] = old_fixture

        self.assertEqual(ontology["source"], "codex-second-brain-starter-kit")
        self.assertEqual(ontology["product"]["slug"], "acme")
        self.assertIn("customer advocates", ontology["product_purpose"])
        self.assertIn("Customer Advocacy", ontology["capabilities"])
        self.assertIn("GET /campaigns", ontology["apis"])
        self.assertIn("type:Campaign", ontology["data_entities"])
        self.assertIn("campaign test", ontology["test_map"])
        self.assertEqual(ontology["fields"]["product_purpose"]["confidence"], "medium")
        self.assertEqual(ontology["fields"]["product_purpose"]["citations"][0]["source_type"], "support")

    def test_product_ontology_v2_rejects_readme_images_and_extracts_business_value(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_ontology_v2_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": []},
            },
            {
                "capabilities": [
                    {
                        "key": "workspace-intelligence",
                        "title": "Workspace Intelligence",
                        "description": "Searchable workspace intelligence for support and product teams.",
                        "keywords": ["workspace", "support", "intelligence"],
                        "repos": ["acme-app"],
                    }
                ]
            },
        )
        support_record = {
            "item": {
                "title": "Acme Workspace Overview",
                "source_url": "https://support.example.com/article/200",
                "relative_path": "200-workspace.md",
            },
            "text": "Support managers use Acme to find product answers faster, reduce repeat escalations, and keep customer-facing guidance current.",
            "signals": {
                "title": "Acme Workspace Overview",
                "headings": ["Overview"],
                "bullets": ["Support managers reduce repeat escalations with current product guidance."],
                "paragraphs": [
                    "Support managers use Acme to find product answers faster, reduce repeat escalations, and keep customer-facing guidance current."
                ],
            },
            "source_ref": "200-workspace.md",
        }

        old_fixture = os.environ.get("PRODUCT_BASB_BUSINESS_VALUE_FIXTURE")
        os.environ["PRODUCT_BASB_BUSINESS_VALUE_FIXTURE"] = "1"
        try:
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
                        "readme_summary": '<img src="https://example.com/logo.png" width="30%">',
                        "top_dirs": ["src"],
                        "key_files": ["package.json"],
                        "monorepo_services": ["api"],
                        "monorepo_apps": ["web"],
                    }
                ],
                capability_rows=[
                    {
                        "title": "Workspace Intelligence",
                        "link": "[[Workspace Intelligence]]",
                        "support_count": 1,
                        "wiki_count": 0,
                        "repos": ["acme-app"],
                        "code_count": 1,
                        "code_reference_links": ["[[Code Ref - acme-app - src -- search.py|acme-app/src/search.py:1]]"],
                    }
                ],
                code_intel={
                    "summary": {"route_count": 1, "schema_count": 0, "test_anchor_count": 1},
                    "repos": [{"repo": "acme-app", "test_anchor_count": 1}],
                    "files": [{"repo": "acme-app", "relative_path": "src/search.py", "dependencies": []}],
                    "graph": {
                        "routes": [{"from": "acme-app/src/search.py", "to": "GET /answers"}],
                        "schemas": [],
                        "tests": [{"from": "acme-app/tests/test_search.py", "to": "search freshness test"}],
                    },
                },
                external_links=[],
                docx_extracts=[],
            )
        finally:
            if old_fixture is None:
                os.environ.pop("PRODUCT_BASB_BUSINESS_VALUE_FIXTURE", None)
            else:
                os.environ["PRODUCT_BASB_BUSINESS_VALUE_FIXTURE"] = old_fixture

        self.assertEqual(ontology["schema_version"], 2)
        self.assertNotIn("<img", ontology["product_purpose"])
        self.assertIn("Support managers", ontology["product_purpose"])
        self.assertEqual(ontology["target_personas"][0]["name"], "Support managers")
        self.assertIn("reduce repeat escalations", ontology["business_value_drivers"][0]["business_value"])
        self.assertEqual(ontology["capabilities_v2"][0]["title"], "Workspace Intelligence")
        self.assertIn("user_problem", ontology["capabilities_v2"][0])

    def test_product_ontology_works_for_docs_only_project_without_code(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_docs_only_ontology_test")
        module.configure_runtime(
            {
                "product": {"name": "Docs Product", "slug": "docs-product"},
                "sources": {"stale_doc_hosts": []},
            },
            {
                "capabilities": [
                    {
                        "key": "escalation-workflows",
                        "title": "Escalation Workflows",
                        "description": "Documented workflows for support escalation ownership.",
                        "keywords": ["support", "workflow", "escalation"],
                        "repos": [],
                    }
                ]
            },
        )
        repo_document = {
            "id": "repo-doc:handbook:docs/escalation.md",
            "source_kind": "repo-doc",
            "repo": "handbook",
            "relative_path": "docs/escalation.md",
            "title": "Escalation Workflow",
            "summary": "Support managers use escalation workflows to route customer issues to owners and reduce repeated escalations.",
            "source_uri": "handbook/docs/escalation.md",
            "confidence": "medium",
            "terms": ["support managers", "escalation workflows", "owners"],
        }

        old_fixture = os.environ.get("PRODUCT_BASB_BUSINESS_VALUE_FIXTURE")
        os.environ["PRODUCT_BASB_BUSINESS_VALUE_FIXTURE"] = "1"
        try:
            ontology = module.build_product_ontology(
                manifest={"product": {"name": "Docs Product", "slug": "docs-product"}},
                support_records=[],
                wiki_records=[],
                repo_snapshots=[],
                repo_documents=[repo_document],
                capability_rows=[
                    {
                        "title": "Escalation Workflows",
                        "link": "[[Escalation Workflows]]",
                        "support_count": 0,
                        "wiki_count": 0,
                        "repos": [],
                        "code_count": 0,
                        "code_reference_links": [],
                    }
                ],
                code_intel={"summary": {}, "repos": [], "files": [], "graph": {"routes": [], "schemas": [], "tests": []}},
                external_links=[],
                docx_extracts=[],
            )
        finally:
            if old_fixture is None:
                os.environ.pop("PRODUCT_BASB_BUSINESS_VALUE_FIXTURE", None)
            else:
                os.environ["PRODUCT_BASB_BUSINESS_VALUE_FIXTURE"] = old_fixture

        self.assertEqual(ontology["schema_version"], 2)
        self.assertIn("Support managers", ontology["product_purpose"])
        self.assertEqual(ontology["fields"]["product_purpose"]["citations"][0]["source_type"], "repo-doc")
        self.assertEqual(ontology["capabilities_v2"][0]["code_surfaces"], [])
        self.assertIn("Escalation Workflows", ontology["capabilities"])

    def test_product_ontology_repairs_unusable_gpt_purpose_with_ai_synthesis(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_ontology_repair_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": []},
            },
            {
                "capabilities": [
                    {
                        "key": "workspace-intelligence",
                        "title": "Workspace Intelligence",
                        "description": "Searchable workspace intelligence.",
                        "keywords": ["workspace", "intelligence"],
                        "repos": ["acme-app"],
                    }
                ]
            },
        )
        bad_synthesis = {
            "product_purpose": '<img src="https://example.com/logo.png">',
            "target_personas": [{"name": "Support managers", "problem": "Need answers.", "desired_outcome": "Fewer escalations."}],
            "business_value_drivers": [{"business_value": "Fewer repeated escalations."}],
            "capabilities": [{"title": "Workspace Intelligence", "user_problem": "Need answers.", "business_value": "Faster support."}],
            "workflows": [{"name": "Answer support question"}],
        }
        repaired_synthesis = {
            **bad_synthesis,
            "product_purpose": "Acme helps support managers turn product evidence into grounded answers and fewer repeated escalations.",
        }

        with mock.patch.object(module, "synthesize_business_value", side_effect=[bad_synthesis, repaired_synthesis]) as synthesize:
            ontology = module.build_product_ontology(
                manifest={"product": {"name": "Acme", "slug": "acme"}},
                support_records=[],
                wiki_records=[],
                repo_snapshots=[
                    {
                        "name": "acme-app",
                        "role": "primary",
                        "branch": "main",
                        "readme_title": "Acme",
                        "readme_summary": "Acme helps support managers find grounded product answers.",
                        "top_dirs": ["src"],
                        "key_files": ["README.md"],
                        "monorepo_services": ["api"],
                        "monorepo_apps": ["web"],
                    }
                ],
                capability_rows=[
                    {
                        "title": "Workspace Intelligence",
                        "link": "[[Workspace Intelligence]]",
                        "support_count": 0,
                        "wiki_count": 0,
                        "repos": ["acme-app"],
                        "code_count": 1,
                    }
                ],
                code_intel={"summary": {}, "files": [], "graph": {"routes": [], "schemas": [], "tests": []}},
                external_links=[],
                docx_extracts=[],
            )

        self.assertEqual(synthesize.call_count, 2)
        self.assertEqual(synthesize.call_args_list[1].args[0], "product_ontology_repair")
        self.assertNotIn("<img", ontology["product_purpose"])
        self.assertIn("support managers", ontology["product_purpose"])

    def test_business_value_normalization_accepts_structured_value_score(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_business_value_score_test")

        fields = module.normalized_business_value_fields(
            {
                "target_persona": "Support managers",
                "user_problem": "Need grounded answers.",
                "business_value": "Reduce escalations.",
                "success_metric": "Fewer repeat tickets.",
                "value_score": {"score": "8", "rationale": "High leverage"},
                "evidence_confidence": "high",
                "implementation_leverage": "Reuse the source index.",
            },
            require_user_problem=True,
        )

        self.assertEqual(fields["value_score"], 8)

    def test_business_value_normalization_formats_structured_fields_for_markdown(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_business_value_markdown_test")

        fields = module.normalized_business_value_fields(
            {
                "target_persona": {"name": "Support managers", "rationale": "They own escalations."},
                "user_problem": {"problem": "Need grounded answers.", "impact": "Repeat escalations."},
                "business_value": {"business_value": "Reduce escalations.", "rationale": "Evidence is reusable."},
                "success_metric": ["Fewer repeated tickets", "Faster evidence-backed answers"],
                "value_score": {"score": 86, "rationale": "High leverage"},
                "evidence_confidence": {"level": "high", "rationale": "Support and code evidence agree."},
                "implementation_leverage": {"summary": "Use linked code references and packet evidence."},
            },
            require_user_problem=True,
        )

        self.assertEqual(fields["target_persona"], "Support managers")
        self.assertEqual(fields["user_problem"], "Need grounded answers.")
        self.assertEqual(fields["business_value"], "Reduce escalations.")
        self.assertEqual(fields["success_metric"], "Fewer repeated tickets; Faster evidence-backed answers")
        self.assertEqual(fields["success_metric_markdown"], "- Fewer repeated tickets\n- Faster evidence-backed answers")
        self.assertEqual(fields["evidence_confidence"], "high: Support and code evidence agree.")
        self.assertEqual(fields["value_score"], 9)
        for key in ("target_persona", "user_problem", "business_value", "success_metric", "evidence_confidence", "implementation_leverage"):
            self.assertNotIn("{", fields[key])
            self.assertNotIn("[", fields[key])

    def test_output_candidate_note_formats_structured_business_value_without_gpt_call(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_output_markdown_test")
        packet = {
            "title": "Workspace Intelligence",
            "link": "[[Packet - Workspace Intelligence]]",
            "support_links": ["[[Support - Answers]]"],
            "wiki_links": [],
            "code_reference_links": ["[[Code Ref - Search]]"],
            "conflict_links": [],
            "shard_insight_links": [],
            "evidence_score": 8,
        }
        output_synthesis = {
            "target_persona": {"name": "Support managers"},
            "user_problem": "Need grounded answers.",
            "business_value": "Reduce escalations.",
            "success_metric": ["Fewer repeated tickets", "Faster evidence-backed answers"],
            "value_score": 8,
            "evidence_confidence": {"level": "high", "rationale": "Cited support and code evidence."},
            "implementation_leverage": "Use the linked search code reference.",
        }

        with mock.patch.object(module, "synthesize_business_value", side_effect=AssertionError("renderer called GPT")):
            note = module.build_output_candidate_note(packet, output_synthesis=output_synthesis)

        self.assertIn("- Fewer repeated tickets", note)
        self.assertIn("- Faster evidence-backed answers", note)
        self.assertIn("high: Cited support and code evidence.", note)
        self.assertNotIn("['Fewer", note)
        self.assertNotIn("{'level'", note)

    def test_value_traceability_matrix_links_only_relevant_output_candidates(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_traceability_selective_test")
        module.configure_runtime(
            {"product": {"name": "Acme", "slug": "acme"}, "sources": {"stale_doc_hosts": []}},
            {"capabilities": []},
        )
        product_ontology = {
            "target_personas": [{"name": "Support managers"}],
            "jobs_to_be_done": [{"job": "Answer customers from trusted workspace evidence."}],
        }
        capability_rows = [
            {
                "title": "Workspace Intelligence",
                "link": "[[Capability - Workspace Intelligence]]",
                "target_persona": "Support managers",
                "user_problem": "Need trusted workspace answers.",
                "business_value": "Reduce escalations with cited answers.",
                "support_count": 2,
                "wiki_count": 1,
                "repo_doc_count": 0,
                "code_count": 1,
                "code_reference_links": ["[[Code Ref - search]]"],
            }
        ]
        outputs = [
            {
                "title": "Workspace Intelligence Output Candidate",
                "link": "[[Output Candidate - Workspace Intelligence]]",
                "source_packet": "[[Packet - Workspace Intelligence]]",
                "target_persona": "Support managers",
                "user_problem": "Need trusted workspace answers.",
                "business_value": "Reduce escalations with cited answers.",
                "evidence_links": ["[[Capability - Workspace Intelligence]]", "[[Code Ref - search]]"],
                "source_packet_title": "Workspace Intelligence",
                "value_score": 8,
            },
            {
                "title": "Billing Cleanup Output Candidate",
                "link": "[[Output Candidate - Billing Cleanup]]",
                "target_persona": "Finance admins",
                "user_problem": "Need invoice cleanup.",
                "business_value": "Reduce billing risk.",
                "evidence_links": ["[[Billing]]"],
                "value_score": 7,
            },
        ]

        note = module.build_value_traceability_matrix_note(product_ontology, capability_rows, outputs)
        report = module.build_business_value_report(product_ontology, capability_rows, outputs)

        self.assertIn("[[Output Candidate - Workspace Intelligence]]", note)
        self.assertNotIn("[[Output Candidate - Billing Cleanup]]", note)
        self.assertIn("relevance", note)
        self.assertEqual(report["overbroad_traceability_rows"], 0)
        self.assertLessEqual(report["avg_output_links_per_traceability_row"], 3)

    def test_capability_note_does_not_render_raw_status_dict_for_empty_links(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_capability_status_markdown_test")
        module.configure_runtime(
            {"product": {"name": "Acme", "slug": "acme"}, "sources": {"stale_doc_hosts": []}},
            {"capabilities": []},
        )

        note = module.build_capability_note(
            capability={"key": "docs", "title": "Documented Workflows", "description": "Workflow evidence."},
            support_links=[],
            wiki_links=[],
            repo_note_links=[],
            code_hits=[],
            code_reference_links=[],
            link_records=[],
            business_value={
                "target_persona": "Support managers",
                "user_problem": "Need current guidance.",
                "business_value": "Faster decisions from docs.",
                "success_metric": "Fewer repeated escalations.",
                "value_score": 7,
                "evidence_confidence": "medium",
                "implementation_leverage": "Use document anchors.",
            },
        )

        self.assertIn("Linked pages by status: `None observed`", note)
        self.assertNotIn("{'none': 0}", note)

    def test_product_ontology_normalizes_percentage_value_scores_to_ten_point_scale(self) -> None:
        module = load_module(MODULE_PATH, "rebuild_product_brain_ontology_value_score_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": []},
            },
            {
                "capabilities": [
                    {
                        "key": "workspace-intelligence",
                        "title": "Workspace Intelligence",
                        "description": "Searchable workspace intelligence.",
                        "keywords": ["workspace"],
                        "repos": ["acme-app"],
                    }
                ]
            },
        )
        synthesis = {
            "product_purpose": "Acme helps support managers find grounded product answers.",
            "target_personas": [{"name": "Support managers", "problem": "Need answers.", "desired_outcome": "Fewer escalations."}],
            "business_value_drivers": [{"business_value": "Fewer repeated escalations."}],
            "capabilities": [{"title": "Workspace Intelligence", "user_problem": "Need answers.", "business_value": "Faster support.", "value_score": 94}],
            "workflows": [{"name": "Answer support question"}],
        }

        with mock.patch.object(module, "synthesize_business_value", return_value=synthesis):
            ontology = module.build_product_ontology(
                manifest={"product": {"name": "Acme", "slug": "acme"}},
                support_records=[],
                wiki_records=[],
                repo_snapshots=[
                    {
                        "name": "acme-app",
                        "role": "primary",
                        "branch": "main",
                        "readme_title": "Acme",
                        "readme_summary": "Acme helps support managers find grounded product answers.",
                        "top_dirs": ["src"],
                        "key_files": ["README.md"],
                        "monorepo_services": ["api"],
                        "monorepo_apps": ["web"],
                    }
                ],
                capability_rows=[],
                code_intel={"summary": {}, "files": [], "graph": {"routes": [], "schemas": [], "tests": []}},
                external_links=[],
                docx_extracts=[],
            )

        self.assertEqual(ontology["capabilities_v2"][0]["value_score"], 9)

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
