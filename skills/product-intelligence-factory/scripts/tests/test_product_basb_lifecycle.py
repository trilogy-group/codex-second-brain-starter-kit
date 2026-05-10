from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_DIR.parents[2]
REBUILD_SCRIPT = TOOLS_DIR / "rebuild_product_brain.py"
AUDIT_SCRIPT = REPO_ROOT / "skills" / "obsidian-intelligence-system" / "scripts" / "audit_vault.py"
MIGRATE_SCRIPT = REPO_ROOT / "skills" / "obsidian-intelligence-system" / "scripts" / "migrate_to_product_basb.py"
READINESS_SCRIPT = REPO_ROOT / "skills" / "product-engineering-ops" / "scripts" / "generate_engineering_readiness.py"


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ProductBasbLifecycleTests(unittest.TestCase):
    def test_product_ontology_note_renders_jobs_to_be_done_with_problem_outcome_confidence_and_evidence(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_product_ontology_markdown_test")
        ontology = {
            "product_purpose": "Helps product teams turn source evidence into shippable work.",
            "target_personas": [],
            "jobs_to_be_done": [
                {
                    "job": "Understand product purpose quickly",
                    "user_problem": "Teams need the product purpose without reading every source.",
                    "desired_outcome": "They can explain what to build, why it matters, and where it lives.",
                    "confidence": "high",
                    "evidence": [
                        {"title": "README", "path": "README.md"},
                        {"title": "Architecture", "citation_uri": "docs/architecture.md"},
                    ],
                }
            ],
            "business_value_drivers": [],
            "capabilities_v2": [],
        }

        body = module.build_product_ontology_note(ontology, {"ontology_quality_score": 10})

        self.assertIn("**Understand product purpose quickly**", body)
        self.assertIn("Problem: Teams need the product purpose without reading every source.", body)
        self.assertIn("Outcome: They can explain what to build, why it matters, and where it lives.", body)
        self.assertIn("Confidence: `high`", body)
        self.assertIn("Evidence: `README.md`, `docs/architecture.md`", body)
        self.assertNotIn("**Understand product purpose quickly**: \n", body)

    def test_output_candidate_selection_is_capped_and_uses_packet_evidence(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_product_brain_lifecycle_test")
        packets = [
            {
                "title": f"Packet {index}",
                "stem": f"Packet {index}",
                "link": f"[[Packet {index}]]",
                "support_links": [f"[[Support {index}]]"],
                "wiki_links": [],
                "repo_note_links": [],
                "code_reference_links": [f"[[Code {index}]]"],
                "conflict_links": [],
                "conflict_count": 0,
                "stale_doc_count": 0,
                "evidence_score": 10 - (index % 3),
            }
            for index in range(15)
        ]

        selected = module.select_output_candidates(packets)
        body = module.build_output_candidate_note(
            selected[0],
            output_synthesis={
                "target_persona": "Product and engineering teams",
                "user_problem": "Teams need packet evidence converted into a shippable draft.",
                "business_value": "Traceable output drafts reduce repeated analysis.",
                "success_metric": "The draft links evidence and implementation anchors.",
                "value_score": 7,
                "evidence_confidence": "medium",
                "implementation_leverage": "Start from the packet and verify linked code references.",
            },
        )

        self.assertEqual(len(selected), 12)
        self.assertIn("type: \"output\"", body)
        self.assertIn("output_kind: \"pull-request-plan\"", body)
        self.assertIn("source_packet:", body)
        self.assertIn("evidence_score:", body)
        self.assertIn("shipping_path:", body)
        self.assertIn("target_persona:", body)
        self.assertIn("user_problem:", body)
        self.assertIn("business_value:", body)
        self.assertIn("success_metric:", body)
        self.assertIn("value_score:", body)
        self.assertIn("evidence_confidence:", body)
        self.assertIn("## User problem", body)
        self.assertIn("## Business value", body)
        self.assertIn("## Success metric", body)
        self.assertIn("## Evidence", body)
        self.assertIn("[[Packet", body)

    def test_weekly_review_and_stale_archive_notes_include_lifecycle_sections(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_product_brain_review_archive_test")
        packet = {
            "title": "Platform Core",
            "link": "[[Packet - Platform Core]]",
            "evidence_score": 8,
        }
        output = {
            "link": "[[Output Candidate - Platform Core]]",
            "output_kind": "spec",
            "evidence_score": 8,
        }
        stale_refs = [
            {
                "url": "https://legacy.example.com/page",
                "source_refs": ["support/100.md"],
            }
        ]

        review = module.build_weekly_review_note([packet], [output], stale_refs, {"documentation-drift": ["[[Support 100]]: drift"]})
        archive = module.build_stale_sources_archive_note(stale_refs)

        self.assertIn("type: \"review\"", review)
        self.assertIn("review_period: \"weekly\"", review)
        self.assertIn("## Output candidates", review)
        self.assertIn("[[Output Candidate - Platform Core]]", review)
        self.assertIn("type: \"archive-record\"", archive)
        self.assertIn("archive_reason: \"stale-documentation\"", archive)
        self.assertIn("https://legacy.example.com/page", archive)

    def test_packet_notes_include_generated_output_candidate_backlinks(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_product_brain_packet_backlink_test")
        body = module.build_intermediate_packet_note(
            capability={
                "key": "platform-core",
                "title": "Platform Core",
                "description": "Core product behavior.",
            },
            support_links=["[[Support 1]]"],
            wiki_links=[],
            repo_note_links=[],
            code_reference_links=["[[Code Ref 1]]"],
            output_candidate_links=["[[Output Candidate - Platform Core]]"],
            business_value={
                "target_persona": "Product and engineering teams",
                "user_problem": "Teams need reusable platform evidence.",
                "business_value": "Reusable packets reduce repeated discovery.",
                "success_metric": "The packet can feed an output candidate.",
                "value_score": 6,
                "evidence_confidence": "medium",
                "implementation_leverage": "Validate the linked code reference before shipping.",
            },
        )

        self.assertIn("generated_output_candidates:", body)
        self.assertIn("[[Output Candidate - Platform Core]]", body)
        self.assertIn("## Can feed", body)

    def test_audit_flags_lifecycle_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault = Path(tmp_dir) / "vault"
            vault.mkdir()
            (vault / "Packet.md").write_text(
                "\n".join(
                    [
                        "---",
                        "type: intermediate-packet",
                        "area: acme",
                        "status: reusable",
                        "date: 2026-05-01",
                        "source: generated",
                        "basb_stage: distill",
                        "para_category: resource",
                        "distillation_level: executive",
                        "actionability: soon",
                        "---",
                        "# Packet",
                        "",
                        "## Source evidence",
                        "- [[Evidence]]",
                    ]
                )
            )
            (vault / "Output.md").write_text(
                "\n".join(
                    [
                        "---",
                        "type: output",
                        "area: acme",
                        "status: proposed",
                        "date: 2026-05-01",
                        "output_kind: ticket",
                        "evidence_score: 7",
                        "shipping_path: Create a ticket.",
                        "basb_stage: express",
                        "para_category: project",
                        "distillation_level: executive",
                        "actionability: now",
                        "---",
                        "# Output",
                        "",
                        "## Evidence",
                        "- No link yet",
                    ]
                )
            )
            (vault / "Evidence.md").write_text(
                "\n".join(
                    [
                        "---",
                        "type: insight",
                        "area: acme",
                        "status: active",
                        "basb_stage: distill",
                        "para_category: resource",
                        "distillation_level: distilled",
                        "actionability: soon",
                        "---",
                        "# Evidence",
                        "- [[Packet]]",
                    ]
                )
            )
            completed = subprocess.run(
                [sys.executable, str(AUDIT_SCRIPT), "--vault", str(vault)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("## Outputs Missing Evidence Links", completed.stdout)
        self.assertIn("## Outputs Missing Source Packet", completed.stdout)
        self.assertIn("## Outputs Missing Business Value", completed.stdout)
        self.assertIn("## Packets Without Forward Use", completed.stdout)
        self.assertIn("## Missing Weekly Reviews", completed.stdout)

    def test_audit_flags_blank_ontology_sections_and_empty_jtbd_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault = Path(tmp_dir) / "vault"
            vault.mkdir()
            (vault / "Product Ontology.md").write_text(
                "\n".join(
                    [
                        "---",
                        "type: hub",
                        "source: generated",
                        "---",
                        "# Product Ontology",
                        "",
                        "## Jobs to be done",
                        "",
                        "- **Understand the product**: ",
                        "",
                        "## Business value drivers",
                        "",
                        "## Capabilities",
                    ]
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(AUDIT_SCRIPT), "--vault", str(vault)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("## Generated Template Residue", completed.stdout)
        self.assertIn("empty Product Ontology section", completed.stdout)
        self.assertIn("empty Product Ontology JTBD body", completed.stdout)

    def test_readiness_reports_basb_quality_metrics(self) -> None:
        module = load_module(READINESS_SCRIPT, "readiness_basb_lifecycle_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            (vault / "40 Research" / "Intermediate Packets").mkdir(parents=True)
            (vault / "30 Initiatives" / "Output Candidates").mkdir(parents=True)
            (vault / "70 Journal" / "Reviews").mkdir(parents=True)
            (vault / "90 Archive").mkdir(parents=True)
            (vault / "40 Research" / "Intermediate Packets" / "Packet.md").write_text(
                "---\ntype: intermediate-packet\narea: acme\nstatus: reusable\ndate: 2026-05-01\nbasb_stage: distill\npara_category: resource\ndistillation_level: executive\nactionability: soon\n---\n# Packet\n- [[Output Pipeline]]\n"
            )
            (vault / "30 Initiatives" / "Output Candidates" / "Output.md").write_text(
                "---\ntype: output\narea: acme\nstatus: proposed\ndate: 2026-05-01\nsource_packet: \"[[Packet]]\"\noutput_kind: spec\nevidence_score: 8\nshipping_path: Draft a spec.\nbasb_stage: express\npara_category: project\ndistillation_level: executive\nactionability: now\n---\n# Output\n## Evidence\n- [[Packet]]\n"
            )
            (vault / "70 Journal" / "Reviews" / "Weekly Review - 2026-05-01.md").write_text(
                "---\ntype: review\narea: acme\nstatus: active\ndate: 2026-05-01\nreview_period: weekly\nbasb_stage: distill\npara_category: resource\ndistillation_level: executive\nactionability: now\ntags:\n  - weekly-review\n---\n# Review\n- [[Output]]\n"
            )
            inventory_dir = root / "mirror" / "inventories"
            inventory_dir.mkdir(parents=True)
            (inventory_dir / "code_intelligence.json").write_text(
                '{"summary":{"parsed_files":12,"parse_failures":1,"ast_parsed_files":9,"ast_node_count":120,"route_count":2,"schema_count":3,"test_anchor_count":4,"dependency_edges":5},"graph":{"dependencies":[{"from":"a","to":"b"}]}}\n'
            )
            (inventory_dir / "semantic_clusters.json").write_text(
                '{"clusters":[{"id":"semantic-cluster-1"}],"stats":{"cache_hits":8,"cache_misses":2,"openai_failures":0,"llm_cache_hits":3,"llm_cache_misses":1,"llm_failures":0}}\n'
            )
            (inventory_dir / "business_value_report.json").write_text(
                '{"ontology_quality_score":8.5,"persona_count":2,"jobs_to_be_done_count":3,"business_value_driver_count":2,"business_evidence_gaps":["Billing"]}\n'
            )
            (inventory_dir / "embedding_cache.json").write_text('{"items":{"a":{},"b":{}}}\n')
            (inventory_dir / "llm_cluster_cache.json").write_text('{"items":{"cluster":{}}}\n')
            manifest = {
                "product": {"name": "Acme", "slug": "acme", "mode": "product", "vault_path": str(vault), "workspace_path": str(root)},
                "sources": {"corpus_path": str(root / "corpus"), "mirror_path": str(root / "mirror")},
                "repositories": {"local_clone_root": str(root / "repos"), "safe_mirror_root": str(root / "mirrors"), "items": []},
                "automation_pack": {},
                "engineering_readiness": {"categories": []},
            }

            report = module.render_report(manifest, root / "manifest.yaml")

        self.assertIn("## Product BASB Quality Metrics", report)
        self.assertIn("- Intermediate packets: `1`", report)
        self.assertIn("- Output candidates: `1`", report)
        self.assertIn("- Output conversion rate: `100%`", report)
        self.assertIn("- Weekly reviews: `1`", report)
        self.assertIn("## Code Intelligence And Semantic Metrics", report)
        self.assertIn("- Parsed files: `12`", report)
        self.assertIn("- AST parsed files: `9`", report)
        self.assertIn("- AST nodes: `120`", report)
        self.assertIn("- Semantic clusters: `1`", report)
        self.assertIn("- Embedding cache hit rate: `80%`", report)
        self.assertIn("- LLM synthesis cache hits: `3`", report)
        self.assertIn("- Ontology quality score: `8.5`", report)
        self.assertIn("- Personas: `2`", report)
        self.assertIn("- Jobs to be done: `3`", report)
        self.assertIn("- Business value drivers: `2`", report)
        self.assertIn("- Business evidence gaps: `1`", report)

    def test_migration_dry_run_and_write_create_surfaces_without_overwriting_user_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault = Path(tmp_dir) / "vault"
            (vault / "00 Home").mkdir(parents=True)
            output_pipeline = vault / "00 Home" / "Output Pipeline.md"
            output_pipeline.write_text(
                "---\ntype: hub\nsource: human\n---\n# Custom Output Pipeline\n"
            )

            dry_run = subprocess.run(
                [sys.executable, str(MIGRATE_SCRIPT), "--vault", str(vault), "--product-slug", "acme"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("Mode: `dry-run`", dry_run.stdout)
            self.assertFalse((vault / "40 Research" / "Intermediate Packets" / "Intermediate Packet Index.md").exists())

            write_run = subprocess.run(
                [sys.executable, str(MIGRATE_SCRIPT), "--vault", str(vault), "--product-slug", "acme", "--write"],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Mode: `write`", write_run.stdout)
            self.assertTrue((vault / "40 Research" / "Intermediate Packets" / "Intermediate Packet Index.md").exists())
            self.assertEqual(output_pipeline.read_text(), "---\ntype: hub\nsource: human\n---\n# Custom Output Pipeline\n")


if __name__ == "__main__":
    unittest.main()
