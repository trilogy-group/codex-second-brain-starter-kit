from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from http.client import InvalidURL
from pathlib import Path
from unittest import mock
from urllib.error import URLError


TOOLS_DIR = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = TOOLS_DIR / "build_source_indices.py"
REBUILD_SCRIPT = TOOLS_DIR / "rebuild_product_brain.py"
INIT_MANIFEST_SCRIPT = TOOLS_DIR / "init_product_manifest.py"
WIZARD_SCRIPT = TOOLS_DIR.parents[2] / "scripts" / "second_brain_wizard.py"


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

    def test_hash_prefixed_support_articles_keep_local_evidence_urls(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_hash_support_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            corpus = root / "corpus"
            corpus.mkdir()
            source = corpus / "109d036617194ac5ae4830ffdc2ba80c_49888-article.md"
            source.write_text(
                "\n".join(
                    [
                        "# Invite Users Directly to Translated Content",
                        "",
                        "https://support.acme.test/article/49888-invite-users-directly-to-translated-content",
                        "https://hubname.acme.test/join/starter?lang=fr",
                    ]
                )
            )
            paths = module.Paths(
                workspace=root / "workspace",
                vault=root / "vault",
                corpus=corpus,
                mirror=root / "mirror",
                docx_extract=root / "docx",
                repos_root=root / "repos",
                links_dir=root / "mirror" / "external-pages",
                json_dir=root / "mirror" / "inventories",
            )
            settings = {
                "product_name": "Acme",
                "product_slug": "acme",
                "support_article_url_template": "https://support.acme.test/article/{article_id}",
                "stale_doc_hosts": set(),
            }

            articles, links = module.collect_support_articles(paths, settings)
            records = module.build_link_inventory(
                links,
                paths,
                settings,
                known_local_support_urls={item["source_url"] for item in articles if item.get("source_url")},
            )

        self.assertEqual(articles[0]["article_id"], "49888")
        self.assertEqual(articles[0]["source_url"], "https://support.acme.test/article/49888")
        self.assertEqual(list(links), ["https://support.acme.test/article/49888-invite-users-directly-to-translated-content"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "local-support-evidence")

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
                    "https://support.example.com/article/12345-how-to-use-it": {"support/reference.md"},
                },
                paths,
                settings,
                known_local_support_urls={"https://support.example.com/article/12345"},
            )

        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["status"] == "local-support-evidence" for record in records))

    def test_support_url_normalization_handles_slugs_queries_fragments_and_slashes(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_support_url_normalization_test")

        normalized = {
            module.normalize_known_support_url(url)
            for url in [
                "https://support.example.com/article/12345",
                "https://support.example.com/article/12345-how-to-use-it",
                "https://support.example.com/article/12345-how-to-use-it/",
                "https://support.example.com/article/12345-how-to-use-it/?preview=1",
                "https://support.example.com/article/12345-how-to-use-it#faq",
            ]
        }

        self.assertEqual(normalized, {"https://support.example.com/article/12345"})

    def test_placeholder_urls_are_not_collected_as_external_evidence(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_placeholder_url_test")

        self.assertIsNone(module.sanitize_url("https://hubname.acme.test/join/starter?lang=fr"))
        self.assertIsNone(module.sanitize_url("https://yourhub.acme.test/join/starter"))

    def test_malformed_urls_are_skipped_during_sanitization(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_malformed_url_test")

        self.assertIsNone(module.sanitize_url("https://[broken-host.example.test/path"))

    def test_credentialed_urls_are_redacted_before_inventory(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_credentialed_url_test")

        sanitized = module.sanitize_url("https://oauth2:secret-token@gitlab.acme.test/group/project/-/issues/1")

        self.assertEqual(sanitized, "https://gitlab.acme.test/group/project/-/issues/1")
        self.assertNotIn("secret-token", sanitized)

    def test_non_latin1_urls_are_blocked_without_fetching(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_non_latin1_url_test")

        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(module, "urlopen") as mocked_urlopen:
                result = module.fetch_url(
                    "https://*.example.com\u201d",
                    ["50121-article.md"],
                    Path(tmp_dir),
                    {"stale_doc_hosts": set()},
                )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("non-Latin-1", result["error"])
        mocked_urlopen.assert_not_called()

    def test_invalid_fetch_urls_are_blocked_without_secret_leakage(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_invalid_url_test")

        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(
                module,
                "urlopen",
                side_effect=InvalidURL("nonnumeric port: 'secret-token@gitlab.example.com'"),
            ):
                result = module.fetch_url(
                    "https://gitlab.example.com/group/project",
                    ["50121-article.md"],
                    Path(tmp_dir),
                    {"stale_doc_hosts": set()},
                )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("Invalid URL", result["error"])
        self.assertNotIn("secret-token", result["error"])

    def test_fetch_url_uses_verified_ssl_context(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_ssl_context_test")

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getcode(self):
                return 200

            def geturl(self):
                return "https://support.example.com/article/12345"

            def read(self, _size):
                return b"<html><title>Support Article</title><body>Public evidence</body></html>"

        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(module, "urlopen", return_value=FakeResponse()) as mocked_urlopen:
                result = module.fetch_url(
                    "https://support.example.com/article/12345",
                    ["12345-article.md"],
                    Path(tmp_dir),
                    {"stale_doc_hosts": set()},
                )

        self.assertEqual(result["status"], "mirrored")
        self.assertIsNotNone(mocked_urlopen.call_args.kwargs.get("context"))

    def test_url_errors_are_reported_as_transient_fetch_errors(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_url_error_status_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                mock.patch.object(module, "urlopen", side_effect=URLError(OSError(-3, "Temporary failure in name resolution"))) as mocked_urlopen,
                mock.patch.object(module.time, "sleep"),
            ):
                result = module.fetch_url(
                    "https://support.example.com/article/49888",
                    ["49888-article.md"],
                    Path(tmp_dir),
                    {"stale_doc_hosts": set()},
                )

        self.assertEqual(result["status"], "transient-fetch-error")
        self.assertTrue(result["transient_error"])
        self.assertEqual(result["retry_count"], 3)
        self.assertEqual(mocked_urlopen.call_count, 3)
        self.assertIn("Temporary failure in name resolution", result["error"])

    def test_transient_url_error_retries_then_mirrors_successful_response(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_url_retry_success_test")

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getcode(self):
                return 200

            def geturl(self):
                return "https://support.example.com/article/49888-invite-users-directly-to-translated-content"

            def read(self, _size):
                return b"<html><title>Support Article</title><body>Recovered public evidence</body></html>"

        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                mock.patch.object(
                    module,
                    "urlopen",
                    side_effect=[
                        URLError(OSError(-3, "Temporary failure in name resolution")),
                        FakeResponse(),
                    ],
                ) as mocked_urlopen,
                mock.patch.object(module.time, "sleep"),
            ):
                result = module.fetch_url(
                    "https://support.example.com/article/49888",
                    ["49888-article.md"],
                    Path(tmp_dir),
                    {"stale_doc_hosts": set()},
                )

        self.assertEqual(result["status"], "mirrored")
        self.assertEqual(result["retry_count"], 2)
        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual(result["final_url"], "https://support.example.com/article/49888-invite-users-directly-to-translated-content")

    def test_public_article_with_sign_in_to_comment_is_not_auth_gated(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_public_comment_auth_test")

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getcode(self):
                return 200

            def geturl(self):
                return "https://support.example.com/article/49888"

            def read(self, _size):
                return (
                    b"<html><title>Public Article</title><body>"
                    b"Invite users directly to translated content with language parameters. "
                    b"FAQ content is visible. Please sign in to comment."
                    b"</body></html>"
                )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(module, "urlopen", return_value=FakeResponse()):
                result = module.fetch_url(
                    "https://support.example.com/article/49888",
                    ["49888-article.md"],
                    Path(tmp_dir),
                    {"stale_doc_hosts": set()},
                )

        self.assertEqual(result["status"], "mirrored")

    def test_real_login_wall_is_auth_gated(self) -> None:
        module = load_module(BUILD_SCRIPT, "build_source_indices_real_auth_gate_test")

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getcode(self):
                return 200

            def geturl(self):
                return "https://support.example.com/private"

            def read(self, _size):
                return b"<html><title>Sign in</title><body>Sign in to continue. Email Password Single sign-on</body></html>"

        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(module, "urlopen", return_value=FakeResponse()):
                result = module.fetch_url(
                    "https://support.example.com/private",
                    ["private.md"],
                    Path(tmp_dir),
                    {"stale_doc_hosts": set()},
                )

        self.assertEqual(result["status"], "auth-gated")

    def test_build_and_rebuild_use_local_support_evidence_for_hash_prefixed_articles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            corpus = root / "corpus"
            workspace = root / "workspace"
            vault = root / "vault"
            mirror = root / "mirror"
            profile = workspace / "config" / "intelligence-profile.yaml"
            manifest = root / "manifest.yaml"
            corpus.mkdir()
            profile.parent.mkdir(parents=True)
            (corpus / "109d036617194ac5ae4830ffdc2ba80c_49888-article.md").write_text(
                "\n".join(
                    [
                        "# Invite Users Directly to Translated Content",
                        "",
                        "Invite users directly to a translated sign-up page.",
                        "",
                        "https://support.acme.test/article/49888-invite-users-directly-to-translated-content",
                        "https://hubname.acme.test/join/starter?lang=fr",
                    ]
                )
            )
            profile.write_text(
                "\n".join(
                    [
                        "semantic_clustering:",
                        "  provider: openai",
                        "  embedding_model: text-embedding-3-small",
                        "  min_cluster_size: 3",
                        "  similarity_threshold: 0.78",
                        "  max_clusters: 40",
                        "  llm_model: gpt-5.5",
                        "  reasoning_effort: xhigh",
                        "  llm_cluster_synthesis: false",
                        "  max_llm_clusters: 0",
                        "code_intelligence:",
                        "  max_files_per_repo: 10",
                        "  include_git_history: false",
                        "  include_tests: true",
                        "  include_dependency_graph: true",
                        "  parser_mode: regex-fallback",
                        "capabilities:",
                        "  - key: platform-core",
                        "    title: Platform Core",
                        "    description: Core support behavior.",
                        "    keywords:",
                        "      - invite",
                        "      - translated",
                        "    repos: []",
                    ]
                )
            )
            manifest.write_text(
                "\n".join(
                    [
                        "product:",
                        "  name: Acme",
                        "  slug: acme",
                        "  mode: hybrid",
                        f"  vault_path: {vault}",
                        f"  workspace_path: {workspace}",
                        "sources:",
                        f"  corpus_path: {corpus}",
                        f"  mirror_path: {mirror}",
                        f"  docx_extract_path: {workspace / 'docx'}",
                        "  support_article_url_template: https://support.acme.test/article/{article_id}",
                        "  stale_doc_hosts: []",
                        "profile:",
                        f"  intelligence_path: {profile}",
                        "repositories:",
                        f"  local_clone_root: {workspace / 'repos'}",
                        "  safe_mirror_root: /tmp/acme-mirrors",
                        "  items: []",
                    ]
                )
            )
            env = {**os.environ, "PRODUCT_BASB_EMBEDDING_FIXTURE": "1"}

            subprocess.run([sys.executable, str(BUILD_SCRIPT), "--manifest", str(manifest)], check=True, env=env, capture_output=True, text=True)
            subprocess.run([sys.executable, str(REBUILD_SCRIPT), "--manifest", str(manifest)], check=True, env=env, capture_output=True, text=True)

            external_links = (mirror / "inventories" / "external_links.json").read_text()
            support_note = next((vault / "40 Research" / "Support Articles").glob("Support - 49888 - *.md")).read_text()

        self.assertIn('"status": "local-support-evidence"', external_links)
        self.assertNotIn("hubname.acme.test", external_links)
        self.assertIn("Invite users directly to a translated sign-up page.", support_note)
        self.assertNotIn("## Uncaptured evidence", support_note)

    def test_empty_capability_repos_default_to_manifest_repositories(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_product_brain_default_capability_repos_test")
        manifest = {
            "product": {"name": "Acme", "slug": "acme"},
            "sources": {"stale_doc_hosts": []},
            "repositories": {
                "items": [
                    {"name": "repo-one", "local_path": "/tmp/repo-one"},
                    {"name": "repo-two", "local_path": "/tmp/repo-two"},
                ]
            },
        }
        profile = {
            "capabilities": [
                {
                    "key": "platform-core",
                    "title": "Platform Core",
                    "description": "Core behavior.",
                    "keywords": ["settings"],
                    "repos": [],
                },
                {
                    "key": "api",
                    "title": "API",
                    "description": "API behavior.",
                    "keywords": ["api"],
                    "repos": ["repo-two"],
                },
            ]
        }

        module.configure_runtime(manifest, profile)

        self.assertEqual(module.CAPABILITIES[0]["repos"], ["repo-one", "repo-two"])
        self.assertEqual(module.CAPABILITIES[1]["repos"], ["repo-two"])

    def test_rebuild_generates_code_references_when_capability_repos_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            vault = root / "vault"
            corpus = root / "corpus"
            mirror = root / "mirror"
            repo = workspace / "repos" / "repo-one"
            profile = workspace / "config" / "intelligence-profile.yaml"
            manifest = root / "manifest.yaml"
            (repo / "src").mkdir(parents=True)
            corpus.mkdir()
            vault.mkdir()
            profile.parent.mkdir(parents=True)
            (repo / "src" / "settings.py").write_text(
                "\n".join(
                    [
                        "class Settings:",
                        "    def load_settings(self):",
                        "        return {'homepage': 'dashboard'}",
                    ]
                ),
                encoding="utf-8",
            )
            profile.write_text(
                "\n".join(
                    [
                        "semantic_clustering:",
                        "  provider: openai",
                        "  embedding_model: text-embedding-3-small",
                        "  min_cluster_size: 3",
                        "  similarity_threshold: 0.78",
                        "  max_clusters: 40",
                        "  llm_model: gpt-5.5",
                        "  reasoning_effort: xhigh",
                        "  llm_cluster_synthesis: false",
                        "  max_llm_clusters: 0",
                        "code_intelligence:",
                        "  max_files_per_repo: 20",
                        "  include_git_history: false",
                        "  include_tests: true",
                        "  include_dependency_graph: true",
                        "  parser_mode: regex-fallback",
                        "generation_performance:",
                        "  agent_shards:",
                        "    enabled: false",
                        "capabilities:",
                        "  - key: platform-core",
                        "    title: Platform Core",
                        "    description: Core behavior.",
                        "    keywords:",
                        "      - settings",
                        "      - dashboard",
                        "    repos: []",
                    ]
                ),
                encoding="utf-8",
            )
            manifest.write_text(
                "\n".join(
                    [
                        "product:",
                        "  name: Acme",
                        "  slug: acme",
                        "  mode: hybrid",
                        f"  vault_path: {vault}",
                        f"  workspace_path: {workspace}",
                        "sources:",
                        f"  corpus_path: {corpus}",
                        f"  mirror_path: {mirror}",
                        f"  docx_extract_path: {workspace / 'docx'}",
                        "  support_article_url_template: ''",
                        "  stale_doc_hosts: []",
                        "profile:",
                        f"  intelligence_path: {profile}",
                        "repositories:",
                        f"  local_clone_root: {workspace / 'repos'}",
                        "  safe_mirror_root: /tmp/acme-mirrors",
                        "  items:",
                        "    - owner: acme",
                        "      name: repo-one",
                        "      role: source-repository",
                        "      default_branch: main",
                        f"      local_path: {repo}",
                        "      url: https://github.com/acme/repo-one",
                    ]
                ),
                encoding="utf-8",
            )
            env = {**os.environ, "PRODUCT_BASB_EMBEDDING_FIXTURE": "1"}

            subprocess.run([sys.executable, str(BUILD_SCRIPT), "--manifest", str(manifest)], check=True, env=env, capture_output=True, text=True)
            subprocess.run([sys.executable, str(REBUILD_SCRIPT), "--manifest", str(manifest)], check=True, env=env, capture_output=True, text=True)

            code_refs = list((vault / "40 Research" / "Code Intelligence" / "References").glob("*.md"))
            capability_note = (vault / "20 Product" / "Capabilities" / "Capability - Platform Core.md").read_text(encoding="utf-8")
            capability_map = (vault / "20 Product" / "Product Capability Map.md").read_text(encoding="utf-8")

        self.assertTrue(code_refs)
        self.assertIn("[[Code Ref - repo-one - src -- settings.py|repo-one/src/settings.py:1]]", capability_note)
        self.assertIn("- Code hits: `1`", capability_map)
        self.assertIn("[[Code Ref - repo-one - src -- settings.py|repo-one/src/settings.py:1]]", capability_map)

    def test_code_intelligence_hits_can_anchor_capabilities_without_rg_hits(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_product_brain_code_intelligence_hits_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo-one"
            source_path = repo_root / "src" / "auth" / "sessions.py"
            source_path.parent.mkdir(parents=True)
            source_path.write_text("def authenticate_session():\n    return True\n", encoding="utf-8")
            capability = {
                "key": "identity-and-access",
                "title": "Identity And Access",
                "description": "Authentication, authorization, roles, sessions, and sign-in flows.",
                "keywords": ["login", "authentication", "session"],
                "repos": ["repo-one"],
            }
            code_files = [
                {
                    "repo": "repo-one",
                    "relative_path": "src/auth/sessions.py",
                    "language": "python",
                    "symbols": {"functions": ["authenticate_session"]},
                    "symbol_count": 1,
                    "routes": [],
                    "schemas": [],
                    "tests": [],
                    "dependencies": [],
                    "imports": [],
                    "calls": [],
                    "line_start": 1,
                }
            ]

            hits = module.code_intelligence_hits_for_capability(
                code_files,
                capability,
                {"repo-one": repo_root},
                limit=10,
            )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["repo"], "repo-one")
        self.assertEqual(hits[0]["relative_path"], "src/auth/sessions.py")
        self.assertEqual(hits[0]["absolute_path"], str(source_path))
        self.assertEqual(hits[0]["retrieval_source"], "code-intelligence")

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

    def test_wizard_refresh_rebuilds_indices_and_vault_before_metadata(self) -> None:
        module = load_module(WIZARD_SCRIPT, "second_brain_wizard_refresh_test")
        registry = {
            "brains": [
                {
                    "name": "Acme",
                    "slug": "acme",
                    "manifest_path": "/tmp/portfolio/manifests/acme.yaml",
                    "vault_path": "/tmp/portfolio/vaults/Acme",
                    "audit_path": "/tmp/portfolio/vaults/Acme/80 Assets/vault-audit.md",
                    "readiness_report_path": "/tmp/portfolio/workspaces/acme/reports/acme.md",
                }
            ]
        }
        commands: list[list[str]] = []

        with (
            mock.patch.object(module, "ensure_registry_exists", return_value=registry),
            mock.patch.object(module, "write_yaml"),
            mock.patch.object(module, "run", side_effect=commands.append),
        ):
            result = module.refresh(Path("/tmp/portfolio"), "acme")

        self.assertEqual(result, 0)
        command_text = [" ".join(command) for command in commands]
        self.assertIn(str(module.VALIDATE_MANIFEST), command_text[0])
        self.assertIn(str(module.BUILD_SOURCE_INDICES), command_text[1])
        self.assertIn(str(module.REBUILD_PRODUCT_BRAIN), command_text[2])
        self.assertIn(str(module.AUDIT_VAULT), command_text[3])
        self.assertIn(str(module.GENERATE_READINESS), command_text[4])

    def test_wizard_metadata_only_refresh_skips_vault_rebuild(self) -> None:
        module = load_module(WIZARD_SCRIPT, "second_brain_wizard_metadata_only_test")
        registry = {
            "brains": [
                {
                    "name": "Acme",
                    "slug": "acme",
                    "manifest_path": "/tmp/portfolio/manifests/acme.yaml",
                    "vault_path": "/tmp/portfolio/vaults/Acme",
                    "audit_path": "/tmp/portfolio/vaults/Acme/80 Assets/vault-audit.md",
                    "readiness_report_path": "/tmp/portfolio/workspaces/acme/reports/acme.md",
                }
            ]
        }
        commands: list[list[str]] = []

        with (
            mock.patch.object(module, "ensure_registry_exists", return_value=registry),
            mock.patch.object(module, "write_yaml"),
            mock.patch.object(module, "run", side_effect=commands.append),
        ):
            result = module.refresh(Path("/tmp/portfolio"), "acme", metadata_only=True)

        self.assertEqual(result, 0)
        command_text = "\n".join(" ".join(command) for command in commands)
        self.assertNotIn(str(module.BUILD_SOURCE_INDICES), command_text)
        self.assertNotIn(str(module.REBUILD_PRODUCT_BRAIN), command_text)
        self.assertIn(str(module.AUDIT_VAULT), command_text)
        self.assertIn(str(module.GENERATE_READINESS), command_text)

    def test_wizard_refresh_force_passes_force_to_heavy_generators(self) -> None:
        module = load_module(WIZARD_SCRIPT, "second_brain_wizard_force_refresh_test")
        registry = {
            "brains": [
                {
                    "name": "Acme",
                    "slug": "acme",
                    "manifest_path": "/tmp/portfolio/manifests/acme.yaml",
                    "vault_path": "/tmp/portfolio/vaults/Acme",
                    "audit_path": "/tmp/portfolio/vaults/Acme/80 Assets/vault-audit.md",
                    "readiness_report_path": "/tmp/portfolio/workspaces/acme/reports/acme.md",
                }
            ]
        }
        commands: list[list[str]] = []

        with (
            mock.patch.object(module, "ensure_registry_exists", return_value=registry),
            mock.patch.object(module, "write_yaml"),
            mock.patch.object(module, "run", side_effect=commands.append),
        ):
            result = module.refresh(Path("/tmp/portfolio"), "acme", force=True)

        self.assertEqual(result, 0)
        self.assertIn("--force", commands[1])
        self.assertIn("--force", commands[2])
        self.assertNotIn("--force", commands[0])

    def test_readme_documents_large_source_performance_guidance(self) -> None:
        readme = TOOLS_DIR.parents[2] / "README.md"
        body = readme.read_text(encoding="utf-8")

        self.assertIn("## Performance for large source sets", body)
        self.assertIn("500+ sources", body)
        self.assertIn("benchmark_rebuild.py", body)
        self.assertIn("--force", body)
        self.assertIn("sources.mirror_path", body)
        self.assertIn("rebuild_timings.json", body)
        self.assertIn("rate_limit_events.json", body)
        self.assertNotIn("support.influitive.com", body)

    def test_readme_documents_retrieval_guided_warm_rebuilds(self) -> None:
        readme = TOOLS_DIR.parents[2] / "README.md"
        body = readme.read_text(encoding="utf-8")

        self.assertIn("## Retrieval-guided warm rebuilds", body)
        self.assertIn("retrieval_index:", body)
        self.assertIn("changed_scope_rebuild: true", body)
        self.assertIn("evidence_index.sqlite", body)
        self.assertIn("evidence_index_manifest.json", body)
        self.assertIn("changed_scope_report.json", body)
        self.assertIn("retrieval-changed-scope", body)
        self.assertIn("SQLite FTS", body)
        self.assertIn("does not require a vector database", body)


if __name__ == "__main__":
    unittest.main()
