from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = TOOLS_DIR / "build_source_indices.py"
REBUILD_SCRIPT = TOOLS_DIR / "rebuild_product_brain.py"
INIT_MANIFEST_SCRIPT = TOOLS_DIR / "init_product_manifest.py"


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GenericToolingTests(unittest.TestCase):
    def test_generic_script_names_replace_product_specific_names(self) -> None:
        legacy_slug = "example-product"
        legacy_build_script = TOOLS_DIR / f"build_{legacy_slug}_indices.py"
        legacy_rebuild_script = TOOLS_DIR / f"rebuild_{legacy_slug}_brain.py"

        self.assertTrue(BUILD_SCRIPT.exists(), "expected generic build script to exist")
        self.assertTrue(REBUILD_SCRIPT.exists(), "expected generic rebuild script to exist")
        self.assertFalse(legacy_build_script.exists(), "product-specific build script should be removed")
        self.assertFalse(legacy_rebuild_script.exists(), "product-specific rebuild script should be removed")

    def test_init_product_manifest_includes_profile_and_enhanced_source_defaults(self) -> None:
        module = load_module(INIT_MANIFEST_SCRIPT, "init_product_manifest_under_test")

        class Args:
            name = "Acme"
            slug = "acme"
            mode = "hybrid"
            vault = Path("/tmp/vault")
            workspace = Path("/tmp/workspace")

        manifest = module.build_manifest(Args())

        self.assertEqual(
            Path(manifest["profile"]["intelligence_path"]).name,
            "intelligence-profile.yaml",
        )
        self.assertEqual(
            Path(manifest["profile"]["intelligence_path"]).parent.name,
            "config",
        )
        self.assertEqual(manifest["sources"]["support_article_url_template"], "")
        self.assertEqual(manifest["sources"]["stale_doc_hosts"], [])
        self.assertGreaterEqual(len(manifest["engineering_readiness"]["categories"]), 8)

    def test_source_settings_are_manifest_driven(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_under_test")
        manifest = {
            "product": {
                "name": "Acme",
                "slug": "acme",
                "workspace_path": "/tmp/workspace",
                "vault_path": "/tmp/vault",
            },
            "sources": {
                "corpus_path": "/tmp/corpus",
                "mirror_path": "/tmp/mirror",
                "docx_extract_path": "/tmp/docx",
                "support_article_url_template": "https://support.example.com/article/{article_id}",
                "stale_doc_hosts": ["legacy.example.com"],
            },
            "repositories": {
                "local_clone_root": "/tmp/repos",
                "items": [
                    {
                        "name": "handbook",
                        "role": "engineering-wiki",
                        "local_path": "/tmp/repos/handbook",
                    }
                ],
            },
        }

        settings = module.product_settings(manifest)

        self.assertEqual(
            module.support_source_url("12345", settings),
            "https://support.example.com/article/12345",
        )
        self.assertEqual(module.support_source_url("not-an-article", settings), "")
        self.assertEqual(
            module.repo_path_by_role(manifest, "engineering-wiki"),
            Path("/tmp/repos/handbook"),
        )
        self.assertEqual(
            module.classify_special_url("https://legacy.example.com/wiki/page", settings),
            "stale-doc-reference",
        )

    def test_known_support_urls_are_treated_as_local_evidence(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_local_support_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            paths = module.Paths(
                workspace=root / "workspace",
                vault=root / "vault",
                corpus=root / "corpus",
                mirror=root / "mirror",
                docx_extract=root / "docx",
                repos_root=root / "repos",
                links_dir=root / "mirror" / "external-pages",
                json_dir=root / "mirror" / "inventories",
            )
            settings = {
                "product_name": "Acme",
                "product_slug": "acme",
                "support_article_url_template": "https://support.example.com/article/{article_id}",
                "stale_doc_hosts": set(),
            }

            records = module.build_link_inventory(
                {
                    "https://support.example.com/article/12345": {"support/12345-article.md"},
                },
                paths,
                settings,
                known_local_support_urls={"https://support.example.com/article/12345"},
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "local-support-evidence")

    def test_repo_snapshots_tolerate_missing_repo_paths(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_missing_repo_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest = {
                "repositories": {
                    "items": [
                        {
                            "name": "repo-one",
                            "role": "core-app",
                            "default_branch": "main",
                            "local_path": str(root / "repos" / "repo-one"),
                        }
                    ]
                }
            }
            paths = module.Paths(
                workspace=root / "workspace",
                vault=root / "vault",
                corpus=root / "corpus",
                mirror=root / "mirror",
                docx_extract=root / "docx",
                repos_root=root / "repos",
                links_dir=root / "mirror" / "external-pages",
                json_dir=root / "mirror" / "inventories",
            )

            snapshots = module.collect_repo_snapshots(manifest, paths)

        self.assertEqual(len(snapshots), 1)
        self.assertFalse(snapshots[0]["path_exists"])
        self.assertEqual(snapshots[0]["top_dirs"], [])


if __name__ == "__main__":
    unittest.main()
