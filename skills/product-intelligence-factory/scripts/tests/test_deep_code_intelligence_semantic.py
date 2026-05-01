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


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DeepCodeIntelligenceSemanticTests(unittest.TestCase):
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
        self.assertIn("User", by_path["web.ts"]["symbols"]["types"])
        self.assertIn({"method": "POST", "path": "/login", "source": "service.py"}, by_path["service.py"]["routes"])
        self.assertIn("LOGIN_TOKEN", by_path["service.py"]["env_vars"])
        self.assertIn("User", by_path["main.go"]["symbols"]["classes"])
        self.assertIn("LoginController", by_path["ViewController.swift"]["symbols"]["classes"])
        self.assertIn("LoginWidget", by_path["Widget.m"]["symbols"]["classes"])
        self.assertIn({"kind": "sql-object", "name": "accounts", "source": "migration.sql"}, by_path["migration.sql"]["schemas"])
        self.assertGreaterEqual(by_path["openapi.yaml"]["schema_count"], 2)
        self.assertIn("react", by_path["package.json"]["dependencies"])
        self.assertGreaterEqual(result["summary"]["dependency_edges"], 1)

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
        os.environ["PRODUCT_BASB_EMBEDDING_FIXTURE"] = "1"
        try:
            cards = [
                {"id": "support-1", "kind": "support", "title": "Login failure", "summary": "Session token expires", "capabilities": ["Identity"], "evidence_terms": ["auth"], "code_terms": ["session"]},
                {"id": "wiki-1", "kind": "wiki", "title": "SSO setup", "summary": "Identity provider access", "capabilities": ["Identity"], "evidence_terms": ["sso"], "code_terms": ["permission"]},
                {"id": "code-1", "kind": "code", "title": "AuthController", "summary": "Login session permissions", "capabilities": ["Identity"], "evidence_terms": ["login"], "code_terms": ["auth"]},
            ]
            config = module.default_semantic_config({"semantic_clustering": {"min_cluster_size": 3, "similarity_threshold": 0.4}})
            with tempfile.TemporaryDirectory() as tmp_dir:
                cache_path = Path(tmp_dir) / "embedding_cache.json"
                first = module.cluster_cards(cards, config, cache_path)
                second = module.cluster_cards(cards, config, cache_path)
        finally:
            if original_fixture is None:
                os.environ.pop("PRODUCT_BASB_EMBEDDING_FIXTURE", None)
            else:
                os.environ["PRODUCT_BASB_EMBEDDING_FIXTURE"] = original_fixture

        self.assertEqual(len(first["clusters"]), 1)
        self.assertEqual(first["stats"]["cache_misses"], 3)
        self.assertEqual(second["stats"]["cache_hits"], 3)

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
                "cards": [
                    {
                        "link": "[[Support - Login]]",
                        "source_links": ["[[Support - Login]]"],
                        "code_reference_links": ["[[Code Ref - auth.rb]]"],
                        "code_terms": ["AuthController"],
                    }
                ],
                "limitations": ["Embedding cluster over compact evidence cards."],
            }
        )

        self.assertIn("packet_kind: \"semantic-cluster\"", body)
        self.assertIn("## Theme", body)
        self.assertIn("## Why this cluster exists", body)
        self.assertIn("## Cross-source evidence", body)
        self.assertIn("## Related code surfaces", body)
        self.assertIn("## Output candidates", body)
        self.assertIn("## Cluster limitations", body)


if __name__ == "__main__":
    unittest.main()
