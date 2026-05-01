from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_DIR.parents[2]
SCAFFOLD_SCRIPT = REPO_ROOT / "skills" / "obsidian-intelligence-system" / "scripts" / "scaffold_vault.py"
AUDIT_SCRIPT = REPO_ROOT / "skills" / "obsidian-intelligence-system" / "scripts" / "audit_vault.py"
REBUILD_SCRIPT = TOOLS_DIR / "rebuild_product_brain.py"
INIT_MANIFEST_SCRIPT = TOOLS_DIR / "init_product_manifest.py"


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ProductBasbUpgradeTests(unittest.TestCase):
    def test_scaffold_creates_product_basb_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault = Path(tmp_dir) / "vault"
            subprocess.run(
                [
                    sys.executable,
                    str(SCAFFOLD_SCRIPT),
                    "--vault",
                    str(vault),
                    "--project",
                    "Acme",
                    "--mode",
                    "product",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            expected_paths = [
                vault / "00 Home" / "CODE Dashboard.md",
                vault / "00 Home" / "PARA Map.md",
                vault / "00 Home" / "Output Pipeline.md",
                vault / "40 Research" / "Intermediate Packets" / "Intermediate Packet Index.md",
                vault / "90 Archive" / "Archive Index.md",
                vault / "90 Templates" / "Intermediate Packet Template.md",
                vault / "90 Templates" / "Shippable Output Template.md",
            ]

            for path in expected_paths:
                self.assertTrue(path.exists(), path)

            product_os = (vault / "00 Home" / "Product OS.md").read_text()
            self.assertIn("[[CODE Dashboard]]", product_os)
            self.assertIn("[[Output Pipeline]]", product_os)
            self.assertIn("basb_stage: organize", product_os)

    def test_audit_flags_product_basb_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault = Path(tmp_dir) / "vault"
            vault.mkdir()
            (vault / "Raw Concept.md").write_text(
                "\n".join(
                    [
                        "---",
                        "type: concept",
                        "area: acme",
                        "status: active",
                        "---",
                        "# Raw Concept",
                        "",
                        "- [[Target]]",
                    ]
                )
            )
            (vault / "Output Candidate.md").write_text(
                "\n".join(
                    [
                        "---",
                        "type: output",
                        "area: acme",
                        "status: proposed",
                        "date: 2026-05-01",
                        "basb_stage: express",
                        "para_category: project",
                        "distillation_level: executive",
                        "actionability: now",
                        "---",
                        "# Output Candidate",
                        "",
                        "## Evidence",
                        "",
                        "- No link yet",
                    ]
                )
            )
            (vault / "Target.md").write_text(
                "\n".join(
                    [
                        "---",
                        "type: insight",
                        "area: acme",
                        "status: distilled",
                        "date: 2026-05-01",
                        "basb_stage: distill",
                        "para_category: resource",
                        "distillation_level: distilled",
                        "actionability: soon",
                        "---",
                        "# Target",
                        "",
                        "- [[Raw Concept]]",
                    ]
                )
            )

            completed = subprocess.run(
                [sys.executable, str(AUDIT_SCRIPT), "--vault", str(vault)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("## Missing Product BASB Fields", completed.stdout)
        self.assertIn("Raw Concept.md", completed.stdout)
        self.assertIn("## Outputs Missing Evidence Links", completed.stdout)
        self.assertIn("Output Candidate.md", completed.stdout)

    def test_manifest_defaults_include_product_basb_readiness_categories(self) -> None:
        module = load_module(INIT_MANIFEST_SCRIPT, "init_manifest_basb_test")

        class Args:
            name = "Acme"
            slug = "acme"
            mode = "hybrid"
            vault = Path("/tmp/vault")
            workspace = Path("/tmp/workspace")

        manifest = module.build_manifest(Args())
        keys = {category["key"] for category in manifest["engineering_readiness"]["categories"]}

        self.assertIn("product-basb-alignment", keys)
        self.assertIn("progressive-summarization-coverage", keys)
        self.assertIn("output-conversion-and-archive-hygiene", keys)
        self.assertGreaterEqual(len(keys), 11)

    def test_generated_notes_include_basb_metadata_and_distillation_sections(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_product_brain_basb_note_test")
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
            raw_path.write_text("# Sample Article\n\n## Overview\n\nThis explains platform behavior.\n")
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
                article_note_stems={},
                wiki_note_stems={},
                related_support_links=[],
                related_wiki_links=[],
                code_reference_links=["[[Code Ref - core-repo - app.rb]]"],
                conflicts=[],
            )

        self.assertIn("basb_stage: \"distill\"", body)
        self.assertIn("para_category: \"resource\"", body)
        self.assertIn("capture_quality:", body)
        self.assertIn("## Essence", body)
        self.assertIn("## Use in current project", body)
        self.assertIn("## Full Article Content", body)

    def test_intermediate_packet_note_links_evidence_to_outputs(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_product_brain_packet_test")
        module.configure_runtime(
            {
                "product": {"name": "Acme", "slug": "acme"},
                "sources": {"stale_doc_hosts": []},
            },
            {"capabilities": []},
        )

        body = module.build_intermediate_packet_note(
            capability={
                "key": "platform-core",
                "title": "Platform Core",
                "description": "Core product behavior.",
                "keywords": ["platform"],
                "repos": ["core-repo"],
            },
            support_links=["[[Support - 100 - Sample Article]]"],
            wiki_links=["[[Wiki - Root - Platform]]"],
            repo_note_links=["[[Repo - core-repo]]"],
            code_reference_links=["[[Code Ref - core-repo - app.rb]]"],
        )

        self.assertIn("type: \"intermediate-packet\"", body)
        self.assertIn("basb_stage: \"distill\"", body)
        self.assertIn("[[Output Pipeline]]", body)
        self.assertIn("[[Support - 100 - Sample Article]]", body)

    def test_prompts_do_not_tell_agents_to_store_raw_authentication_details(self) -> None:
        haystack = "\n".join(
            path.read_text(errors="ignore")
            for path in [REPO_ROOT / "README.md", *(REPO_ROOT / "prompts").glob("*.md")]
        ).lower()

        self.assertNotIn("store the authentication details", haystack)
        self.assertIn("approved credential/session storage", haystack)


if __name__ == "__main__":
    unittest.main()
