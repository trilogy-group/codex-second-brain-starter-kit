from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
CODE_INTELLIGENCE_SCRIPT = TOOLS_DIR / "code_intelligence.py"
SEMANTIC_SCRIPT = TOOLS_DIR / "semantic_clustering.py"
REBUILD_SCRIPT = TOOLS_DIR / "rebuild_product_brain.py"
GENERATION_PERFORMANCE_SCRIPT = TOOLS_DIR / "generation_performance.py"
EVIDENCE_INDEX_SCRIPT = TOOLS_DIR / "evidence_index.py"


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DeepCodeIntelligenceSemanticTests(unittest.TestCase):
    def test_generation_performance_defaults_are_fixed_high_concurrency(self) -> None:
        module = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_defaults_test")

        config = module.default_generation_config({})

        self.assertEqual(config["parallel_workers"], 24)
        self.assertEqual(config["source_extract_workers"], 24)
        self.assertEqual(config["source_fetch_workers"], 40)
        self.assertEqual(config["repo_analysis_workers"], 6)
        self.assertEqual(config["code_analysis_workers"], 12)
        self.assertEqual(config["note_render_workers"], 32)
        self.assertEqual(config["embedding_workers"], 8)
        self.assertEqual(config["llm_synthesis_workers"], 10)
        self.assertEqual(config["embedding_batch_size"], 512)
        self.assertTrue(config["incremental_rebuild"])
        self.assertEqual(config["agent_shards"]["max_shards"], 12)
        self.assertEqual(config["agent_shards"]["max_concurrent_shards"], 6)
        self.assertEqual(config["agent_shards"]["timeout_seconds"], 1800)
        self.assertEqual(config["agent_shards"]["worker_mode"], "llm-synthesis")
        self.assertEqual(config["agent_shards"]["shard_model"], "gpt-5.5")
        self.assertEqual(config["agent_shards"]["reasoning_effort"], "high")
        self.assertEqual(config["agent_shards"]["max_cards_per_shard"], 80)
        self.assertTrue(config["changed_scope_rebuild"])

    def test_default_retrieval_index_config_is_enabled_and_validated(self) -> None:
        evidence_index = load_module(EVIDENCE_INDEX_SCRIPT, "evidence_index_config_test")

        default_config = evidence_index.default_retrieval_config({})
        custom_config = evidence_index.default_retrieval_config(
            {"retrieval_index": {"enabled": False, "max_candidates_per_source": 11, "min_score": 0.25}}
        )

        self.assertTrue(default_config["enabled"])
        self.assertEqual(default_config["max_candidates_per_source"], 30)
        self.assertEqual(default_config["min_score"], 0.0)
        self.assertFalse(custom_config["enabled"])
        self.assertEqual(custom_config["max_candidates_per_source"], 11)
        self.assertEqual(custom_config["min_score"], 0.25)
        with self.assertRaises(SystemExit):
            evidence_index.default_retrieval_config({"retrieval_index": {"max_candidates_per_source": 0}})

    def test_retrieval_ranked_code_hits_prefer_index_matches_and_fallback_to_keywords(self) -> None:
        evidence_index = load_module(EVIDENCE_INDEX_SCRIPT, "evidence_index_ranking_test")
        rebuild = load_module(REBUILD_SCRIPT, "rebuild_product_brain_retrieval_ranking_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "evidence_index.sqlite"
            evidence_index.rebuild_index(
                index_path,
                [
                    evidence_index.EvidenceRow(
                        evidence_id="code:billing",
                        kind="code",
                        title="BillingSessionHandler",
                        body="Handles invoice token failures and payment session recovery.",
                        source_ref="repo/app/billing.py",
                        path="repo/app/billing.py",
                        capabilities=["billing"],
                        code_refs=[],
                        fingerprint="billing",
                    ),
                    evidence_index.EvidenceRow(
                        evidence_id="code:auth",
                        kind="code",
                        title="AuthController",
                        body="Handles login session token failures.",
                        source_ref="repo/app/auth.py",
                        path="repo/app/auth.py",
                        capabilities=["identity"],
                        code_refs=[],
                        fingerprint="auth",
                    ),
                ],
            )
            fallback_hits = [
                {"repo": "repo", "relative_path": "app/auth.py", "absolute_path": str(Path(tmp_dir) / "repo" / "app" / "auth.py"), "sample": "session login", "score": 1},
                {"repo": "repo", "relative_path": "app/billing.py", "absolute_path": str(Path(tmp_dir) / "repo" / "app" / "billing.py"), "sample": "invoice payment", "score": 1},
            ]
            ranked = rebuild.retrieval_ranked_code_hits(
                index_path=index_path,
                query="invoice token payment session",
                fallback_hits=fallback_hits,
                limit=2,
                min_score=0.0,
            )
            fallback = rebuild.retrieval_ranked_code_hits(
                index_path=Path(tmp_dir) / "missing.sqlite",
                query="invoice token payment session",
                fallback_hits=fallback_hits,
                limit=2,
                min_score=0.0,
            )

        self.assertEqual([item["relative_path"] for item in ranked], ["app/billing.py", "app/auth.py"])
        self.assertEqual(ranked[0]["retrieval_source"], "sqlite-fts")
        self.assertEqual(fallback, fallback_hits)

    def test_capability_code_ranking_prefers_application_files_over_tests_and_config(self) -> None:
        rebuild = load_module(REBUILD_SCRIPT, "rebuild_product_brain_code_anchor_quality_test")
        hits = [
            {
                "repo": "repo",
                "relative_path": "tests/test_billing.py",
                "absolute_path": "/repo/tests/test_billing.py",
                "sample": "billing invoice payment",
                "score": 100,
            },
            {
                "repo": "repo",
                "relative_path": ".github/workflows/deploy.yml",
                "absolute_path": "/repo/.github/workflows/deploy.yml",
                "sample": "billing deploy",
                "score": 90,
            },
            {
                "repo": "repo",
                "relative_path": "services/billing/invoice_service.py",
                "absolute_path": "/repo/services/billing/invoice_service.py",
                "sample": "billing invoice payment workflow",
                "score": 10,
            },
        ]

        ranked = rebuild.rank_code_hits_for_keywords(hits, ["billing invoice payment"], limit=3)

        self.assertEqual(ranked[0]["relative_path"], "services/billing/invoice_service.py")
        self.assertEqual(ranked[-1]["relative_path"], ".github/workflows/deploy.yml")

    def test_source_extract_workers_default_to_parallel_workers_and_support_env_override(self) -> None:
        module = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_source_extract_test")
        original = os.environ.get("PRODUCT_BASB_SOURCE_EXTRACT_WORKERS")
        os.environ["PRODUCT_BASB_SOURCE_EXTRACT_WORKERS"] = "7"
        try:
            config = module.default_generation_config({"generation_performance": {"parallel_workers": 9}})
        finally:
            if original is None:
                os.environ.pop("PRODUCT_BASB_SOURCE_EXTRACT_WORKERS", None)
            else:
                os.environ["PRODUCT_BASB_SOURCE_EXTRACT_WORKERS"] = original

        self.assertEqual(config["parallel_workers"], 9)
        self.assertEqual(config["source_extract_workers"], 7)

    def test_generation_performance_rejects_auto_mode(self) -> None:
        module = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_auto_test")

        with self.assertRaises(SystemExit):
            module.default_generation_config({"generation_performance": {"parallel_workers": "auto"}})

    def test_multilanguage_code_intelligence_extracts_expected_surfaces(self) -> None:
        module = load_module(CODE_INTELLIGENCE_SCRIPT, "code_intelligence_multilang_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            fixtures = {
                "app.rb": "class AccountsController\n  get '/accounts'\n  def index\n  end\nend\n",
                "web.ts": "import express from 'express';\ninterface User { id: string }\nrouter.post('/users', createUser);\nconst buildUser = () => ({});\n",
                "service.py": "import os\n@app.route('/login', methods=['POST'])\ndef login():\n    return os.getenv('LOGIN_TOKEN')\n",
                "main.go": "package main\nimport \"net/http\"\ntype User struct { ID string }\nfunc main() { http.HandleFunc('/health', health) }\n",
                "ViewController.swift": "class LoginController {\n  func viewDidLoad() {}\n}\n",
                "Widget.m": "@interface LoginWidget : NSObject\n@end\n",
                "migration.sql": "CREATE TABLE accounts (id integer primary key);\n",
                "openapi.yaml": "openapi: 3.0.0\npaths:\n  /accounts: {}\ncomponents:\n  schemas:\n    Account: {}\n",
                "package.json": '{"dependencies":{"react":"latest"},"devDependencies":{"vitest":"latest"}}',
            }
            for relative, body in fixtures.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body)

            result = module.analyze_repositories({"sample-repo": repo}, {"code_intelligence": {"max_files_per_repo": 50, "include_git_history": False}})
            by_path = {item["relative_path"]: item for item in result["files"]}

        self.assertIn("AccountsController", by_path["app.rb"]["symbols"]["classes"])
        self.assertEqual(result["config"]["repo_analysis_workers"], 6)
        self.assertEqual(result["config"]["code_analysis_workers"], 12)
        self.assertIn("User", by_path["web.ts"]["symbols"]["types"])
        self.assertIn({"method": "POST", "path": "/login", "source": "service.py"}, by_path["service.py"]["routes"])
        self.assertIn("LOGIN_TOKEN", by_path["service.py"]["env_vars"])
        self.assertEqual(by_path["service.py"]["parser_backend"], "python-ast")
        self.assertGreater(by_path["service.py"]["ast_node_count"], 0)
        self.assertTrue(by_path["service.py"]["symbol_edges"])
        self.assertTrue(by_path["service.py"]["call_edges"])
        self.assertEqual(by_path["service.py"]["line_start"], 1)
        self.assertGreaterEqual(by_path["service.py"]["line_end"], 3)
        self.assertIn("User", by_path["main.go"]["symbols"]["classes"])
        self.assertIn("LoginController", by_path["ViewController.swift"]["symbols"]["classes"])
        self.assertIn("LoginWidget", by_path["Widget.m"]["symbols"]["classes"])
        self.assertIn({"kind": "sql-object", "name": "accounts", "source": "migration.sql"}, by_path["migration.sql"]["schemas"])
        self.assertGreaterEqual(by_path["openapi.yaml"]["schema_count"], 2)
        self.assertIn("react", by_path["package.json"]["dependencies"])
        self.assertGreaterEqual(result["summary"]["dependency_edges"], 1)
        self.assertGreaterEqual(result["summary"]["ast_parsed_files"], 1)
        self.assertGreater(result["summary"]["ast_node_count"], 0)

    def test_git_tracked_source_mode_excludes_untracked_generated_artifacts(self) -> None:
        module = load_module(CODE_INTELLIGENCE_SCRIPT, "code_intelligence_git_tracked_filter_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            (repo / "src").mkdir()
            (repo / "src" / "app.py").write_text("def useful_feature():\n    return True\n", encoding="utf-8")
            (repo / "cdk.out").mkdir()
            (repo / "cdk.out" / "asset.py").write_text("def generated_asset():\n    return True\n", encoding="utf-8")
            (repo / "scratch.py").write_text("def untracked_scratch():\n    return True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "src/app.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "add source"], check=True, capture_output=True)

            result = module.analyze_repositories(
                {"sample-repo": repo},
                {"code_intelligence": {"max_files_per_repo": 50, "include_git_history": False}},
            )
            paths = {item["relative_path"] for item in result["files"]}

        self.assertEqual(paths, {"src/app.py"})
        self.assertEqual(result["config"]["source_file_mode"], "git-tracked")
        self.assertEqual(result["config"]["include_untracked_code"], False)
        self.assertGreaterEqual(result["summary"]["excluded_untracked_files"], 1)
        self.assertGreaterEqual(result["summary"]["excluded_generated_files"], 1)

    def test_git_history_metrics_extract_churn_and_owner_candidates(self) -> None:
        module = load_module(CODE_INTELLIGENCE_SCRIPT, "code_intelligence_git_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            target = repo / "service.py"
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Ada",
                "GIT_AUTHOR_EMAIL": "ada@example.com",
                "GIT_COMMITTER_NAME": "Ada",
                "GIT_COMMITTER_EMAIL": "ada@example.com",
            }
            target.write_text("def alpha():\n    return 1\n")
            subprocess.run(["git", "add", "service.py"], cwd=repo, check=True, capture_output=True, env=env)
            subprocess.run(["git", "commit", "-m", "first"], cwd=repo, check=True, capture_output=True, env=env)
            target.write_text("def alpha():\n    return 2\n")
            subprocess.run(["git", "add", "service.py"], cwd=repo, check=True, capture_output=True, env=env)
            subprocess.run(["git", "commit", "-m", "second"], cwd=repo, check=True, capture_output=True, env=env)

            result = module.analyze_repositories({"sample-repo": repo}, {"code_intelligence": {"max_files_per_repo": 20, "include_git_history": True}})
            service = next(item for item in result["files"] if item["relative_path"] == "service.py")

        self.assertGreaterEqual(service["churn_score"], 2)
        self.assertIn("Ada", service["owner_candidates"])

    def test_clean_repo_cache_reuses_unchanged_repository_analysis_until_force(self) -> None:
        module = load_module(CODE_INTELLIGENCE_SCRIPT, "code_intelligence_repo_cache_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            target = repo / "service.py"
            target.write_text("def alpha():\n    return 1\n")
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Ada",
                "GIT_AUTHOR_EMAIL": "ada@example.com",
                "GIT_COMMITTER_NAME": "Ada",
                "GIT_COMMITTER_EMAIL": "ada@example.com",
            }
            subprocess.run(["git", "add", "service.py"], cwd=repo, check=True, capture_output=True, env=env)
            subprocess.run(["git", "commit", "-m", "first"], cwd=repo, check=True, capture_output=True, env=env)
            cache_path = Path(tmp_dir) / "rebuild_cache.json"
            profile = {
                "code_intelligence": {"max_files_per_repo": 20, "include_git_history": False},
                "generation_performance": {"incremental_rebuild": True},
            }

            first = module.analyze_repositories({"sample-repo": repo}, profile, cache_path=cache_path)
            second = module.analyze_repositories({"sample-repo": repo}, profile, cache_path=cache_path)
            target.write_text("def alpha():\n    return 2\n\ndef beta():\n    return 3\n")
            dirty = module.analyze_repositories({"sample-repo": repo}, profile, cache_path=cache_path)
            forced = module.analyze_repositories({"sample-repo": repo}, profile, cache_path=cache_path, force=True)

        self.assertEqual(first["summary"]["repo_cache_hits"], 0)
        self.assertEqual(second["summary"]["repo_cache_hits"], 1)
        self.assertEqual(dirty["summary"]["repo_cache_hits"], 0)
        self.assertIn("beta", dirty["files"][0]["symbols"]["functions"])
        self.assertEqual(forced["summary"]["repo_cache_hits"], 0)

    def test_parser_failures_are_partial_and_non_fatal(self) -> None:
        module = load_module(CODE_INTELLIGENCE_SCRIPT, "code_intelligence_parse_failure_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            (repo / "broken.json").write_text('{"dependencies": ')
            result = module.analyze_repositories({"sample-repo": repo}, {"code_intelligence": {"max_files_per_repo": 20, "include_git_history": False}})
            broken = result["files"][0]

        self.assertEqual(broken["parse_quality"], "partial")
        self.assertGreaterEqual(result["summary"]["parse_failures"], 1)
        self.assertTrue(broken["parser_errors"])

    def test_regex_only_parser_mode_keeps_fallback_inventory_fields(self) -> None:
        module = load_module(CODE_INTELLIGENCE_SCRIPT, "code_intelligence_regex_only_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            (repo / "app.js").write_text("function login() { return fetch('/login'); }\n")
            result = module.analyze_repositories(
                {"sample-repo": repo},
                {"code_intelligence": {"max_files_per_repo": 20, "include_git_history": False, "parser_mode": "regex-only"}},
            )
            item = result["files"][0]

        self.assertEqual(item["parser_backend"], "regex-fallback")
        self.assertEqual(item["ast_node_count"], 0)
        self.assertEqual(item["line_start"], 1)
        self.assertEqual(item["line_end"], 1)
        self.assertIn("login", item["symbols"]["functions"])

    def test_openai_key_missing_fails_semantic_clustering(self) -> None:
        module = load_module(SEMANTIC_SCRIPT, "semantic_missing_key_test")
        original_key = os.environ.pop("OPENAI_API_KEY", None)
        original_fixture = os.environ.pop("PRODUCT_BASB_EMBEDDING_FIXTURE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with self.assertRaises(SystemExit):
                    module.cluster_cards(
                        [{"id": "a", "kind": "support", "title": "Login issue", "summary": "Session access problem"}],
                        module.default_semantic_config({}),
                        Path(tmp_dir) / "embedding_cache.json",
                    )
        finally:
            if original_key is not None:
                os.environ["OPENAI_API_KEY"] = original_key
            if original_fixture is not None:
                os.environ["PRODUCT_BASB_EMBEDDING_FIXTURE"] = original_fixture

    def test_fixture_semantic_clustering_groups_related_cards_and_reuses_cache(self) -> None:
        module = load_module(SEMANTIC_SCRIPT, "semantic_fixture_cache_test")
        original_fixture = os.environ.get("PRODUCT_BASB_EMBEDDING_FIXTURE")
        original_llm_fixture = os.environ.get("PRODUCT_BASB_LLM_FIXTURE")
        os.environ["PRODUCT_BASB_EMBEDDING_FIXTURE"] = "1"
        os.environ["PRODUCT_BASB_LLM_FIXTURE"] = "1"
        try:
            cards = [
                {"id": "support-1", "kind": "support", "title": "Login failure", "summary": "Session token expires", "capabilities": ["Identity"], "evidence_terms": ["auth"], "code_terms": ["session"]},
                {"id": "wiki-1", "kind": "wiki", "title": "SSO setup", "summary": "Identity provider access", "capabilities": ["Identity"], "evidence_terms": ["sso"], "code_terms": ["permission"]},
                {"id": "code-1", "kind": "code", "title": "AuthController", "summary": "Login session permissions", "capabilities": ["Identity"], "evidence_terms": ["login"], "code_terms": ["auth"]},
            ]
            config = module.default_semantic_config({"semantic_clustering": {"min_cluster_size": 3, "similarity_threshold": 0.4}})
            self.assertEqual(config["embedding_workers"], 8)
            self.assertEqual(config["embedding_batch_size"], 512)
            self.assertEqual(config["llm_synthesis_workers"], 10)
            with tempfile.TemporaryDirectory() as tmp_dir:
                cache_path = Path(tmp_dir) / "embedding_cache.json"
                first = module.cluster_cards(cards, config, cache_path)
                second = module.cluster_cards(cards, config, cache_path)
        finally:
            if original_fixture is None:
                os.environ.pop("PRODUCT_BASB_EMBEDDING_FIXTURE", None)
            else:
                os.environ["PRODUCT_BASB_EMBEDDING_FIXTURE"] = original_fixture
            if original_llm_fixture is None:
                os.environ.pop("PRODUCT_BASB_LLM_FIXTURE", None)
            else:
                os.environ["PRODUCT_BASB_LLM_FIXTURE"] = original_llm_fixture

        self.assertEqual(len(first["clusters"]), 1)
        self.assertEqual(first["stats"]["cache_misses"], 3)
        self.assertEqual(first["stats"]["llm_cache_misses"], 1)
        self.assertEqual(first["clusters"][0]["llm_synthesis_status"], "succeeded")
        self.assertIn("Synthesized", first["clusters"][0]["theme"])
        self.assertEqual(second["stats"]["cache_hits"], 3)
        self.assertEqual(second["stats"]["llm_cache_hits"], 1)

    def test_llm_synthesis_failure_preserves_embedding_cluster(self) -> None:
        module = load_module(SEMANTIC_SCRIPT, "semantic_llm_failure_test")

        class FailingLLMClient:
            def synthesize_cluster(self, cluster, model):
                raise RuntimeError("planned failure")

        original_fixture = os.environ.get("PRODUCT_BASB_EMBEDDING_FIXTURE")
        os.environ["PRODUCT_BASB_EMBEDDING_FIXTURE"] = "1"
        try:
            cards = [
                {"id": "support-1", "kind": "support", "title": "Login failure", "summary": "Session token expires", "capabilities": ["Identity"], "evidence_terms": ["auth"], "code_terms": ["session"]},
                {"id": "wiki-1", "kind": "wiki", "title": "SSO setup", "summary": "Identity provider access", "capabilities": ["Identity"], "evidence_terms": ["sso"], "code_terms": ["permission"]},
                {"id": "code-1", "kind": "code", "title": "AuthController", "summary": "Login session permissions", "capabilities": ["Identity"], "evidence_terms": ["login"], "code_terms": ["auth"]},
            ]
            config = module.default_semantic_config({"semantic_clustering": {"min_cluster_size": 3, "similarity_threshold": 0.4}})
            with tempfile.TemporaryDirectory() as tmp_dir:
                result = module.cluster_cards(cards, config, Path(tmp_dir) / "embedding_cache.json", llm_client=FailingLLMClient())
        finally:
            if original_fixture is None:
                os.environ.pop("PRODUCT_BASB_EMBEDDING_FIXTURE", None)
            else:
                os.environ["PRODUCT_BASB_EMBEDDING_FIXTURE"] = original_fixture

        self.assertEqual(len(result["clusters"]), 1)
        self.assertEqual(result["clusters"][0]["llm_synthesis_status"], "failed")
        self.assertEqual(result["stats"]["llm_failures"], 1)

    def test_semantic_packet_note_contains_required_progressive_sections(self) -> None:
        module = load_module(REBUILD_SCRIPT, "rebuild_semantic_packet_note_test")
        module.configure_runtime(
            {"product": {"name": "Acme", "slug": "acme"}, "sources": {"stale_doc_hosts": []}},
            {"capabilities": []},
        )
        body = module.build_semantic_packet_note(
            {
                "theme": "Identity Access",
                "similarity_score": 0.91,
                "evidence_score": 8,
                "llm_summary": "Identity access evidence should be reviewed together.",
                "why_this_cluster_exists": "The cards point to the same login path.",
                "merge_split_recommendation": "Keep together.",
                "output_candidate_rationale": "Strong delivery candidate.",
                "llm_synthesis_status": "succeeded",
                "llm_model": "gpt-5.5",
                "llm_reasoning_effort": "high",
                "cards": [
                    {
                        "link": "[[Support - Login]]",
                        "source_links": ["[[Support - Login]]"],
                        "code_reference_links": ["[[Code Ref - auth.rb]]"],
                        "code_terms": ["AuthController"],
                    }
                ],
                "limitations": ["Embedding cluster over compact evidence cards."],
            },
            business_value={
                "target_persona": "Product and engineering teams",
                "user_problem": "Teams need identity evidence reviewed together.",
                "business_value": "Semantic packets reduce duplicated investigation.",
                "success_metric": "The cluster can feed a grounded output candidate.",
                "value_score": 7,
                "evidence_confidence": "medium",
                "implementation_leverage": "Validate the linked AuthController reference.",
            },
        )

        self.assertIn("packet_kind: \"semantic-cluster\"", body)
        self.assertIn("## Theme", body)
        self.assertIn("## Why this cluster exists", body)
        self.assertIn("## Cross-source evidence", body)
        self.assertIn("generated_output_candidates:", body)
        self.assertIn("## LLM synthesis", body)
        self.assertIn("Identity access evidence", body)
        self.assertIn("## Synthesis guidance", body)
        self.assertIn("llm_reasoning_effort: \"high\"", body)
        self.assertIn("## Synthesis status", body)
        self.assertIn("## Related code surfaces", body)
        self.assertIn("## Output candidates", body)
        self.assertIn("## Cluster limitations", body)


if __name__ == "__main__":
    unittest.main()
