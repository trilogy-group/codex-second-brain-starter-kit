from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
GENERATION_PERFORMANCE_SCRIPT = TOOLS_DIR / "generation_performance.py"
GENERATION_SHARDS_SCRIPT = TOOLS_DIR / "generation_shards.py"
INCREMENTAL_CACHE_SCRIPT = TOOLS_DIR / "incremental_cache.py"
NOTE_RENDERING_SCRIPT = TOOLS_DIR / "note_rendering.py"
CODE_INTELLIGENCE_SCRIPT = TOOLS_DIR / "code_intelligence.py"
RATE_LIMITS_SCRIPT = TOOLS_DIR / "rate_limits.py"
SOURCE_INDEX_CACHE_SCRIPT = TOOLS_DIR / "source_index_cache.py"
GENERATION_PROGRESS_SCRIPT = TOOLS_DIR / "generation_progress.py"
OPENAI_REQUESTS_SCRIPT = TOOLS_DIR / "openai_requests.py"
PROMOTE_OUTPUT_CANDIDATE_SCRIPT = TOOLS_DIR / "promote_output_candidate.py"
BENCHMARK_REBUILD_SCRIPT = TOOLS_DIR / "benchmark_rebuild.py"
BUILD_SOURCE_INDICES_SCRIPT = TOOLS_DIR / "build_source_indices.py"
SEMANTIC_SCRIPT = TOOLS_DIR / "semantic_clustering.py"
EVIDENCE_INDEX_SCRIPT = TOOLS_DIR / "evidence_index.py"
EVIDENCE_CARDS_SCRIPT = TOOLS_DIR / "evidence_cards.py"
HIERARCHICAL_REDUCERS_SCRIPT = TOOLS_DIR / "hierarchical_reducers.py"
REBUILD_PRODUCT_BRAIN_SCRIPT = TOOLS_DIR / "rebuild_product_brain.py"
INIT_INTELLIGENCE_PROFILE_SCRIPT = TOOLS_DIR / "init_intelligence_profile.py"


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HighConcurrencyGenerationTests(unittest.TestCase):
    def test_evidence_card_title_quality_rejects_failed_file_summaries(self) -> None:
        evidence_cards = load_module(EVIDENCE_CARDS_SCRIPT, "evidence_cards_title_quality_test")

        self.assertEqual(
            evidence_cards.normalize_title("**Whole File Summary**", fallback="apps/auth/client.ai.md"),
            "Client",
        )
        self.assertEqual(
            evidence_cards.clean_summary("**Whole File Summary**\n\nUnable to summarize file. Maybe too big?"),
            "",
        )
        self.assertTrue(
            evidence_cards.is_invalid_evidence_card({
                "kind": "repo-doc",
                "source_path": ".ai/app.py.ai.md",
                "title": "Whole File Summary",
                "summary": "Unable to summarize file. Maybe too big?",
            })
        )

    def test_evidence_index_skips_failed_generated_summary_rows(self) -> None:
        evidence_index = load_module(EVIDENCE_INDEX_SCRIPT, "evidence_index_bad_summary_skip_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            index_path = root / "evidence_index.sqlite"
            manifest_path = root / "evidence_index_manifest.json"
            rows = [
                evidence_index.EvidenceRow(
                    evidence_id="bad:summary",
                    kind="repo-doc",
                    title="**Whole File Summary**",
                    body="Unable to summarize file. Maybe too big?",
                    source_ref=".ai/app.py.ai.md",
                    path=".ai/app.py.ai.md",
                ),
                evidence_index.EvidenceRow(
                    evidence_id="good:runbook",
                    kind="repo-doc",
                    title="Support Escalation Runbook",
                    body="Support managers route unresolved issues to product owners.",
                    source_ref="docs/runbook.md",
                    path="docs/runbook.md",
                ),
            ]

            stats = evidence_index.rebuild_index(index_path, rows, manifest_path=manifest_path)
            results = evidence_index.search(index_path, "maybe too big", limit=5)
            good_results = evidence_index.search(index_path, "support managers", limit=5)

        self.assertEqual(stats["indexed_rows"], 1)
        self.assertEqual(results, [])
        self.assertEqual([item["evidence_id"] for item in good_results], ["good:runbook"])

    def test_evidence_index_upserts_searches_and_removes_stale_rows(self) -> None:
        evidence_index = load_module(EVIDENCE_INDEX_SCRIPT, "evidence_index_lifecycle_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            index_path = root / "evidence_index.sqlite"
            manifest_path = root / "evidence_index_manifest.json"
            rows = [
                evidence_index.EvidenceRow(
                    evidence_id="support:alpha",
                    kind="support",
                    title="Login troubleshooting",
                    body="Reset session tokens when login access fails.",
                    source_ref="support/alpha.md",
                    path="support/alpha.md",
                    capabilities=["identity"],
                    code_refs=["repo/app/auth.py"],
                    fingerprint="a",
                    metadata={"quality": "high"},
                ),
                evidence_index.EvidenceRow(
                    evidence_id="code:auth",
                    kind="code",
                    title="AuthController",
                    body="Handles session token login failures.",
                    source_ref="repo/app/auth.py",
                    path="repo/app/auth.py",
                    capabilities=["identity"],
                    code_refs=[],
                    fingerprint="b",
                ),
            ]

            stats = evidence_index.rebuild_index(index_path, rows, manifest_path=manifest_path)
            results = evidence_index.search(index_path, "session token login", limit=5)
            stale_stats = evidence_index.rebuild_index(index_path, rows[:1], manifest_path=manifest_path)
            stale_results = evidence_index.search(index_path, "AuthController", limit=5)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertTrue(evidence_index.sqlite_fts_available())
        self.assertEqual(stats["indexed_rows"], 2)
        self.assertEqual([item["evidence_id"] for item in results], ["code:auth", "support:alpha"])
        self.assertEqual(stale_stats["deleted_rows"], 1)
        self.assertEqual(stale_results, [])
        self.assertEqual(manifest["schema_version"], evidence_index.EVIDENCE_INDEX_SCHEMA_VERSION)
        self.assertEqual(manifest["row_count"], 1)

    def test_evidence_index_redacts_sensitive_text_before_upsert(self) -> None:
        evidence_index = load_module(EVIDENCE_INDEX_SCRIPT, "evidence_index_sensitive_text_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "evidence_index.sqlite"
            rows = [
                evidence_index.EvidenceRow(
                    evidence_id="support:secret",
                    kind="support",
                    title="Credentialed runbook",
                    body=(
                        "Fetch https://gitlab+deploy-token-20:secret@gitlab.acme.test/repo.git "
                        "and rotate sk-proj-testtoken_1234567890abcdef."
                    ),
                    source_ref="support@example.com",
                    path="support/secret.md",
                    capabilities=["identity"],
                    code_refs=[],
                )
            ]

            evidence_index.rebuild_index(index_path, rows)
            with sqlite3.connect(index_path) as connection:
                body, source_ref = connection.execute("SELECT body, source_ref FROM evidence").fetchone()

        self.assertNotIn("gitlab+deploy-token-20:secret@", body)
        self.assertNotIn("sk-proj-testtoken_1234567890abcdef", body)
        self.assertNotIn("support@example.com", source_ref)
        self.assertIn("[REDACTED_CREDENTIALS]@", body)
        self.assertIn("[REDACTED_API_KEY]", body)
        self.assertIn("[REDACTED_EMAIL]", source_ref)

    def test_evidence_index_changed_scope_marks_added_modified_deleted_and_force(self) -> None:
        evidence_index = load_module(EVIDENCE_INDEX_SCRIPT, "evidence_index_changed_scope_test")
        previous_rows = [
            evidence_index.EvidenceRow(
                evidence_id="support:alpha",
                kind="support",
                title="Login",
                body="Login fails",
                source_ref="support/alpha.md",
                path="support/alpha.md",
                capabilities=["identity"],
                code_refs=["repo/app/auth.py"],
                fingerprint="old",
            ),
            evidence_index.EvidenceRow(
                evidence_id="support:beta",
                kind="support",
                title="Billing",
                body="Invoice setup",
                source_ref="support/beta.md",
                path="support/beta.md",
                capabilities=["billing"],
                code_refs=[],
                fingerprint="same",
            ),
        ]
        current_rows = [
            evidence_index.EvidenceRow(
                evidence_id="support:alpha",
                kind="support",
                title="Login",
                body="Login fails after SSO",
                source_ref="support/alpha.md",
                path="support/alpha.md",
                capabilities=["identity"],
                code_refs=["repo/app/auth.py"],
                fingerprint="new",
            ),
            evidence_index.EvidenceRow(
                evidence_id="support:gamma",
                kind="support",
                title="Profiles",
                body="Profile setup",
                source_ref="support/gamma.md",
                path="support/gamma.md",
                capabilities=["profiles"],
                code_refs=[],
                fingerprint="fresh",
            ),
        ]

        report = evidence_index.changed_scope_report(previous_rows, current_rows)
        forced = evidence_index.changed_scope_report(previous_rows, current_rows, force=True)

        self.assertEqual(report["changed_counts"]["added"], 1)
        self.assertEqual(report["changed_counts"]["modified"], 1)
        self.assertEqual(report["changed_counts"]["deleted"], 1)
        self.assertEqual(report["impacted_capabilities"], ["billing", "identity", "profiles"])
        self.assertEqual(report["impacted_code_refs"], ["repo/app/auth.py"])
        self.assertFalse(report["force"])
        self.assertEqual(forced["changed_counts"]["unchanged"], 0)
        self.assertEqual(forced["changed_counts"]["modified"], 2)
        self.assertTrue(forced["force"])

    def test_source_extract_cache_reuses_unchanged_markdown_and_force_bypasses(self) -> None:
        build = load_module(BUILD_SOURCE_INDICES_SCRIPT, "build_source_indices_source_cache_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            corpus = root / "corpus"
            corpus.mkdir()
            (corpus / "00100-article.md").write_text("# Alpha\n\nhttps://docs.acme.test/a\n", encoding="utf-8")
            (corpus / "00200-article.md").write_text("# Beta\n\nhttps://docs.acme.test/b\n", encoding="utf-8")
            paths = build.Paths(
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
                "source_extract_workers": 4,
            }
            cache_path = paths.json_dir / "source_extract_cache.json"
            cache = build.load_source_extract_cache(cache_path)
            first_articles, first_links = build.collect_support_articles(paths, settings, source_cache=cache)
            build.write_source_extract_cache(cache_path, cache)
            second_cache = build.load_source_extract_cache(cache_path)
            second_articles, second_links = build.collect_support_articles(paths, settings, source_cache=second_cache)
            forced_cache = build.load_source_extract_cache(cache_path)
            build.collect_support_articles(paths, settings, source_cache=forced_cache, force=True)

        self.assertEqual([item["relative_path"] for item in first_articles], ["00100-article.md", "00200-article.md"])
        self.assertEqual(first_links, second_links)
        self.assertEqual(first_articles, second_articles)
        self.assertEqual(second_cache["stats"]["hits"], 2)
        self.assertEqual(forced_cache["stats"]["force_misses"], 2)

    def test_note_render_manifest_skips_unchanged_notes_and_deletes_stale_generated_notes(self) -> None:
        note_rendering = load_module(NOTE_RENDERING_SCRIPT, "note_rendering_manifest_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            note = vault / "40 Research" / "Support Articles" / "Support - Alpha.md"
            stale = vault / "40 Research" / "Support Articles" / "Support - Stale.md"
            manifest = vault / "80 Assets" / "generated_notes_manifest.json"
            rendered = [
                note_rendering.RenderedNote(note, "# Alpha\n", False, False, "support", "alpha"),
                note_rendering.RenderedNote(stale, "# Stale\n", True, False, "support", "stale"),
            ]

            first = note_rendering.write_rendered_notes(
                rendered,
                write_note=lambda path, body: path.parent.mkdir(parents=True, exist_ok=True) or path.write_text(body, encoding="utf-8"),
                write_generated_note=lambda path, body: path.parent.mkdir(parents=True, exist_ok=True) or path.write_text(body, encoding="utf-8"),
                manifest_path=manifest,
            )
            second = note_rendering.write_rendered_notes(
                [rendered[0]],
                write_note=lambda path, body: path.parent.mkdir(parents=True, exist_ok=True) or path.write_text(body, encoding="utf-8"),
                write_generated_note=lambda path, body: path.parent.mkdir(parents=True, exist_ok=True) or path.write_text(body, encoding="utf-8"),
                manifest_path=manifest,
            )

            self.assertEqual(first["written"], 2)
            self.assertEqual(second["skipped_unchanged"], 1)
            self.assertEqual(second["deleted_stale"], 1)
            self.assertTrue(note.exists())
            self.assertFalse(stale.exists())

    def test_note_render_manifest_never_deletes_stale_user_authored_notes(self) -> None:
        note_rendering = load_module(NOTE_RENDERING_SCRIPT, "note_rendering_user_note_manifest_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            active = vault / "40 Research" / "Active.md"
            user_note = vault / "40 Research" / "User Note.md"
            manifest = vault / "80 Assets" / "generated_notes_manifest.json"
            rendered = [
                note_rendering.RenderedNote(active, "# Active\n", False, False, "support", "active"),
                note_rendering.RenderedNote(user_note, "# User Note\n", False, False, "support", "user"),
            ]

            note_rendering.write_rendered_notes(
                rendered,
                write_note=lambda path, body: path.parent.mkdir(parents=True, exist_ok=True) or path.write_text(body, encoding="utf-8"),
                write_generated_note=lambda path, body: path.parent.mkdir(parents=True, exist_ok=True) or path.write_text(body, encoding="utf-8"),
                manifest_path=manifest,
            )
            second = note_rendering.write_rendered_notes(
                [rendered[0]],
                write_note=lambda path, body: path.parent.mkdir(parents=True, exist_ok=True) or path.write_text(body, encoding="utf-8"),
                write_generated_note=lambda path, body: path.parent.mkdir(parents=True, exist_ok=True) or path.write_text(body, encoding="utf-8"),
                manifest_path=manifest,
            )

            self.assertEqual(second["deleted_stale"], 0)
            self.assertTrue(user_note.exists())

    def test_semantic_result_cache_skips_embedding_and_llm_clients_for_unchanged_inputs(self) -> None:
        semantic = load_module(SEMANTIC_SCRIPT, "semantic_result_cache_test")

        class CountingEmbeddingClient(semantic.FixtureEmbeddingClient):
            def __init__(self) -> None:
                self.calls = 0

            def embed(self, texts: list[str], model: str) -> list[list[float]]:
                self.calls += 1
                return super().embed(texts, model)

        class CountingLLMClient(semantic.FixtureLLMSynthesisClient):
            def __init__(self) -> None:
                self.calls = 0

            def synthesize_cluster(self, cluster: dict, model: str, reasoning_effort: str = "high") -> dict:
                self.calls += 1
                return super().synthesize_cluster(cluster, model, reasoning_effort)

        cards = [
            {"id": "support-1", "kind": "support", "title": "Login failure", "summary": "Session token expires", "capabilities": ["Identity"], "evidence_terms": ["auth"], "code_terms": ["session"]},
            {"id": "wiki-1", "kind": "wiki", "title": "SSO setup", "summary": "Identity provider access", "capabilities": ["Identity"], "evidence_terms": ["sso"], "code_terms": ["permission"]},
            {"id": "code-1", "kind": "code", "title": "AuthController", "summary": "Login session permissions", "capabilities": ["Identity"], "evidence_terms": ["login"], "code_terms": ["auth"]},
        ]
        config = semantic.default_semantic_config({"semantic_clustering": {"min_cluster_size": 3, "similarity_threshold": 0.4}})
        embedding_client = CountingEmbeddingClient()
        llm_client = CountingLLMClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            first = semantic.cluster_cards(
                cards,
                config,
                root / "embedding_cache.json",
                client=embedding_client,
                llm_client=llm_client,
                result_cache_path=root / "semantic_result_cache.json",
            )
            second = semantic.cluster_cards(
                cards,
                config,
                root / "embedding_cache.json",
                client=CountingEmbeddingClient(),
                llm_client=CountingLLMClient(),
                result_cache_path=root / "semantic_result_cache.json",
            )

        self.assertEqual(len(first["clusters"]), 1)
        self.assertEqual(embedding_client.calls, 1)
        self.assertEqual(llm_client.calls, 1)
        self.assertEqual(second["stats"]["result_cache_hits"], 1)
        self.assertEqual(second["stats"]["cache_misses"], 0)
        self.assertEqual(second["stats"]["llm_cache_misses"], 0)

    def test_semantic_force_bypasses_embedding_and_llm_caches(self) -> None:
        semantic = load_module(SEMANTIC_SCRIPT, "semantic_force_cache_test")

        class CountingEmbeddingClient(semantic.FixtureEmbeddingClient):
            def __init__(self) -> None:
                self.calls = 0

            def embed(self, texts: list[str], model: str) -> list[list[float]]:
                self.calls += 1
                return super().embed(texts, model)

        class CountingLLMClient(semantic.FixtureLLMSynthesisClient):
            def __init__(self) -> None:
                self.calls = 0

            def synthesize_cluster(self, cluster: dict, model: str, reasoning_effort: str = "high") -> dict:
                self.calls += 1
                return super().synthesize_cluster(cluster, model, reasoning_effort)

        cards = [
            {"id": "support-1", "kind": "support", "title": "Login failure", "summary": "Session token expires", "capabilities": ["Identity"], "evidence_terms": ["auth"], "code_terms": ["session"]},
            {"id": "wiki-1", "kind": "wiki", "title": "SSO setup", "summary": "Identity provider access", "capabilities": ["Identity"], "evidence_terms": ["sso"], "code_terms": ["permission"]},
            {"id": "code-1", "kind": "code", "title": "AuthController", "summary": "Login session permissions", "capabilities": ["Identity"], "evidence_terms": ["login"], "code_terms": ["auth"]},
        ]
        config = semantic.default_semantic_config({"semantic_clustering": {"min_cluster_size": 3, "similarity_threshold": 0.4}})
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            semantic.cluster_cards(
                cards,
                config,
                root / "embedding_cache.json",
                client=CountingEmbeddingClient(),
                llm_client=CountingLLMClient(),
                result_cache_path=root / "semantic_result_cache.json",
            )
            result_cache_path = root / "semantic_result_cache.json"
            result_cache = json.loads(result_cache_path.read_text(encoding="utf-8"))
            result_cache["items"]["old-stale-fixture-entry"] = {
                "prompt_version": "old",
                "result": {"clusters": [{"limitations": ["Fixture LLM synthesis was used."]}]},
            }
            result_cache_path.write_text(json.dumps(result_cache), encoding="utf-8")
            forced_embedding_client = CountingEmbeddingClient()
            forced_llm_client = CountingLLMClient()
            forced = semantic.cluster_cards(
                cards,
                config,
                root / "embedding_cache.json",
                client=forced_embedding_client,
                llm_client=forced_llm_client,
                result_cache_path=root / "semantic_result_cache.json",
                force=True,
            )
            result_cache_payload = json.loads((root / "semantic_result_cache.json").read_text(encoding="utf-8"))

        self.assertEqual(forced["stats"]["result_cache_hits"], 0)
        self.assertEqual(forced["stats"]["cache_misses"], 3)
        self.assertEqual(forced["stats"]["llm_cache_misses"], 1)
        self.assertEqual(forced_embedding_client.calls, 1)
        self.assertEqual(forced_llm_client.calls, 1)
        self.assertNotIn("old-stale-fixture-entry", result_cache_payload["items"])

    def test_generation_shards_reuse_cached_results_when_specs_match(self) -> None:
        performance = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_shard_cache_test")
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_cache_test")
        calls = 0

        def worker(spec: dict, scratch_dir: Path) -> dict:
            nonlocal calls
            calls += 1
            return shards.default_shard_worker(spec, scratch_dir)

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            cache_path = Path(tmp_dir) / "generation_shard_cache.json"
            config = performance.default_generation_config({})
            first = shards.run_generation_shards(
                generation_config=config,
                workspace_path=workspace,
                repo_names=["repo"],
                support_records=[{"stem": "Support Alpha", "capabilities": ["core"]}],
                wiki_records=[],
                semantic_cards=[],
                run_id="first",
                worker=worker,
                cache_path=cache_path,
            )
            second = shards.run_generation_shards(
                generation_config=config,
                workspace_path=workspace,
                repo_names=["repo"],
                support_records=[{"stem": "Support Alpha", "capabilities": ["core"]}],
                wiki_records=[],
                semantic_cards=[],
                run_id="second",
                worker=worker,
                cache_path=cache_path,
            )

        self.assertEqual(calls, len(first["shards"]))
        self.assertGreaterEqual(second["cache_hits"], 1)
        self.assertTrue(all(item.get("cache_hit") for item in second["shards"]))

    def test_generation_shards_cache_ignores_volatile_card_metadata(self) -> None:
        performance = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_shard_volatile_cache_test")
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_volatile_cache_test")
        calls = 0

        def worker(spec: dict, scratch_dir: Path) -> dict:
            nonlocal calls
            calls += 1
            return shards.default_shard_worker(spec, scratch_dir)

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            cache_path = Path(tmp_dir) / "generation_shard_cache.json"
            config = performance.default_generation_config({})
            first_record = {
                "stem": "Support Alpha",
                "capabilities": ["core"],
                "code_reference_links": ["[[Code Ref - repo - app.py|repo/app.py]] :: old implementation summary"],
                "quality": {
                    "score": 9,
                    "generated_at": "2026-05-10T10:00:00Z",
                    "run_id": "job-a",
                    "scratch_dir": "/tmp/job-a/shard-01",
                    "source_shard_note": "[[Generation Shard - shard-01]]",
                },
            }
            second_record = {
                **first_record,
                "code_reference_links": ["[[Code Ref - repo - app.py|repo/app.py]] :: new generated implementation summary"],
                "quality": {
                    **first_record["quality"],
                    "generated_at": "2026-05-10T11:00:00Z",
                    "run_id": "job-b",
                    "scratch_dir": "/tmp/job-b/shard-01",
                    "source_shard_note": "[[Generation Shard - shard-99]]",
                },
            }
            first = shards.run_generation_shards(
                generation_config=config,
                workspace_path=workspace,
                repo_names=["repo"],
                support_records=[first_record],
                wiki_records=[],
                semantic_cards=[],
                run_id="first",
                worker=worker,
                cache_path=cache_path,
            )
            second = shards.run_generation_shards(
                generation_config=config,
                workspace_path=workspace,
                repo_names=["repo"],
                support_records=[second_record],
                wiki_records=[],
                semantic_cards=[],
                run_id="second",
                worker=worker,
                cache_path=cache_path,
            )

        self.assertEqual(calls, len(first["shards"]))
        self.assertEqual(second["cache_misses"], 0)
        self.assertGreaterEqual(second["cache_hits"], 1)
        self.assertEqual(second["gpt_call_count"], 0)
        self.assertEqual(second["cache_reuse_ratio"], 1.0)
        self.assertTrue(second["current_shard_note_paths"])

    def test_generation_shards_force_ignores_unsupported_cache_schema(self) -> None:
        performance = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_shard_cache_force_test")
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_cache_force_test")
        calls = 0

        def worker(spec: dict, scratch_dir: Path) -> dict:
            nonlocal calls
            calls += 1
            return shards.default_shard_worker(spec, scratch_dir)

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            cache_path = Path(tmp_dir) / "generation_shard_cache.json"
            cache_path.write_text(json.dumps({"schema_version": 1, "entries": {}}), encoding="utf-8")
            config = performance.default_generation_config({})
            result = shards.run_generation_shards(
                generation_config=config,
                workspace_path=workspace,
                repo_names=["repo"],
                support_records=[{"stem": "Support Alpha", "capabilities": ["core"]}],
                wiki_records=[],
                semantic_cards=[],
                run_id="forced",
                worker=worker,
                cache_path=cache_path,
                force=True,
            )
            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertGreater(calls, 0)
        self.assertEqual(result["cache_miss_reasons"], {"force": len(result["shards"])})
        self.assertEqual(cache_payload["schema_version"], 2)

    def test_generation_shards_force_rewrites_supported_cache_without_stale_entries(self) -> None:
        performance = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_shard_cache_force_rewrite_test")
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_cache_force_rewrite_test")

        def worker(spec: dict, scratch_dir: Path) -> dict:
            return shards.default_shard_worker(spec, scratch_dir)

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            cache_path = Path(tmp_dir) / "generation_shard_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "entries": {
                            "old": {
                                "prompt_version": "old",
                                "result": {"status": "succeeded", "llm_status": "fixture"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = performance.default_generation_config({})
            result = shards.run_generation_shards(
                generation_config=config,
                workspace_path=workspace,
                repo_names=["repo"],
                support_records=[{"stem": "Support Alpha", "capabilities": ["core"]}],
                wiki_records=[],
                semantic_cards=[],
                run_id="forced",
                worker=worker,
                cache_path=cache_path,
                force=True,
            )
            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertEqual(len(cache_payload["entries"]), len(result["shards"]))
        self.assertNotIn('"llm_status": "fixture"', json.dumps(cache_payload))

    def test_stable_synthesis_payload_ignores_generated_notes_and_runtime_diagnostics(self) -> None:
        cards = load_module(EVIDENCE_CARDS_SCRIPT, "evidence_cards_stable_synthesis_payload_test")
        first = {
            "title": "Workspace Intelligence",
            "generated_notes_feed_synthesis": False,
            "source_kind_counts": {"repo-doc": 1, "generated-note": 99},
            "hierarchical_reducers": {"layer_stats": {"cache_hits": 10, "elapsed_seconds": 2.5}},
            "evidence_cards": [
                {"id": "doc-1", "source_kind": "repo-doc", "title": "Workflow", "summary": "Support workflow evidence."},
                {"id": "note-1", "source_kind": "generated-note", "title": "Generated Packet", "summary": "Rendered output."},
            ],
            "shard_insight_links": ["[[Generation Shard - old]]"],
            "output_candidate_links": ["[[Output Candidate - old]]"],
        }
        second = {
            **first,
            "date": "2026-05-10",
            "source_kind_counts": {"repo-doc": 1, "generated-note": 1},
            "hierarchical_reducers": {"layer_stats": {"cache_hits": 0, "elapsed_seconds": 99.9}},
            "shard_insight_links": ["[[Generation Shard - new]]"],
            "output_candidate_links": ["[[Output Candidate - new]]"],
        }

        stable_first = cards.stable_synthesis_payload(first)
        stable_second = cards.stable_synthesis_payload(second)

        self.assertEqual(stable_first, stable_second)
        self.assertEqual(stable_first["source_kind_counts"], {"repo-doc": 1})
        self.assertNotIn("generated-note", json.dumps(stable_first))

    def test_changed_scope_for_upstream_synthesis_ignores_generated_rows(self) -> None:
        rebuild = load_module(REBUILD_PRODUCT_BRAIN_SCRIPT, "rebuild_product_brain_upstream_scope_test")
        evidence_index = load_module(EVIDENCE_INDEX_SCRIPT, "evidence_index_upstream_scope_test")
        previous = [
            evidence_index.EvidenceRow(
                evidence_id="support:a",
                kind="support",
                title="Support A",
                body="same",
                source_ref="a",
                path="a",
                capabilities=["core"],
                code_refs=[],
                fingerprint="same",
            ),
            evidence_index.EvidenceRow(
                evidence_id="generated-note:/vault/Packet.md",
                kind="generated-note",
                title="Packet",
                body="old generated note",
                source_ref="/vault/Packet.md",
                path="/vault/Packet.md",
                capabilities=["core"],
                code_refs=["repo/app.py"],
                fingerprint="old",
            ),
        ]
        current = [
            evidence_index.EvidenceRow(
                evidence_id="support:a",
                kind="support",
                title="Support A",
                body="same",
                source_ref="a",
                path="a",
                capabilities=["core"],
                code_refs=[],
                fingerprint="same",
            )
        ]

        report = evidence_index.changed_scope_report(rebuild.upstream_synthesis_rows(previous), current)

        self.assertEqual(report["changed_evidence_ids"], [])
        self.assertEqual(report["impacted_capabilities"], [])

    def test_source_evidence_fingerprint_ignores_derived_code_refs(self) -> None:
        rebuild = load_module(REBUILD_PRODUCT_BRAIN_SCRIPT, "rebuild_product_brain_source_fingerprint_test")
        base_record = {
            "source_ref": "docs/workflow.md",
            "stem": "Support - Workflow",
            "signals": {"title": "Workflow", "headings": ["Workflow"], "bullets": ["Route work"]},
            "text": "Support teams route work to owners.",
            "capabilities": ["workspace-management"],
            "code_hits": [{"repo": "repo", "relative_path": "app/workflows.py"}],
        }
        changed_code_refs = {
            **base_record,
            "code_hits": [{"repo": "repo", "relative_path": "tests/test_workflows.py"}],
        }

        first = rebuild.source_record_to_evidence_row("support", base_record)
        second = rebuild.source_record_to_evidence_row("support", changed_code_refs)

        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_generation_shards_skip_repo_name_placeholder_specs(self) -> None:
        performance = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_no_repo_placeholder_test")
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_no_repo_placeholder_test")
        config = performance.default_generation_config({})

        specs = shards.plan_generation_shards(
            generation_config=config,
            repo_names=["repo-only"],
            support_records=[],
            wiki_records=[],
            semantic_cards=[],
        )

        self.assertEqual(specs, [])

    def test_shard_runner_respects_fixed_shard_caps_and_concurrency(self) -> None:
        performance = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_shard_caps_test")
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_caps_test")
        config = performance.default_generation_config({})
        active = 0
        max_active = 0
        lock = threading.Lock()

        def worker(spec: dict, scratch_dir: Path) -> dict:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            try:
                return shards.default_shard_worker(spec, scratch_dir)
            finally:
                with lock:
                    active -= 1

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            inventory = shards.run_generation_shards(
                generation_config=config,
                workspace_path=workspace,
                repo_names=[f"repo-{index}" for index in range(20)],
                support_records=[{"stem": f"Support {index}", "capabilities": ["core"]} for index in range(30)],
                wiki_records=[{"stem": f"Wiki {index}", "capabilities": ["core"]} for index in range(30)],
                semantic_cards=[{"id": f"card-{index}", "title": f"Card {index}"} for index in range(30)],
                run_id="job-test",
                worker=worker,
            )
            self.assertTrue(all(Path(item["scratch_dir"], "shard_result.json").exists() for item in inventory["shards"]))

        self.assertLessEqual(len(inventory["shards"]), 12)
        self.assertEqual(inventory["max_concurrent_shards"], 6)
        self.assertLessEqual(max_active, 6)
        self.assertTrue(all(item["status"] == "succeeded" for item in inventory["shards"]))

    def test_shard_payload_accepts_single_note_object(self) -> None:
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_single_note_payload_test")

        notes, evidence_cards, shard_insights = shards._validate_shard_payload(
            {
                "notes": {
                    "title": "Identity Synthesis",
                    "summary": "Single-note GPT-5.5 response.",
                    "highlights": ["One"],
                    "distilled_takeaways": ["Two"],
                    "executive_use": ["Use this for planning."],
                    "can_feed": ["Output Pipeline"],
                    "evidence_ids": ["card-1"],
                },
                "evidence_cards": [{"id": "card-1"}],
                "shard_insights": [
                    {
                        "theme": "Identity",
                        "summary": "Identity evidence.",
                        "evidence_ids": ["card-1"],
                        "code_surfaces": [],
                        "output_rationale": "Promote.",
                    }
                ],
            }
        )

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["title"], "Identity Synthesis")
        self.assertEqual(evidence_cards, [{"id": "card-1"}])
        self.assertEqual(shard_insights[0]["theme"], "Identity")

    def test_reducer_rejects_duplicate_stems_bad_frontmatter_bad_links_and_user_overwrites(self) -> None:
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_reducer_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            target_dir = vault / "80 Assets" / "Generation Shards"
            target_dir.mkdir(parents=True)
            (vault / "00 Home").mkdir(parents=True)
            (target_dir / "Existing User.md").write_text("# Existing user note\n", encoding="utf-8")

            inventory = {
                "enabled": True,
                "shards": [],
            }
            cases = {
                "good": ("Good.md", "---\nsource: generated\ntype: shard-record\n---\n# Good\n\n- [[Intelligence Home]]\n"),
                "duplicate-a": ("Duplicate.md", "---\nsource: generated\n---\n# Duplicate\n"),
                "duplicate-b": ("Duplicate.md", "---\nsource: generated\n---\n# Duplicate again\n"),
                "invalid-frontmatter": ("Invalid.md", "# Invalid\n"),
                "missing-source": ("Missing Source.md", "---\ntype: shard-record\n---\n# Missing Source\n"),
                "bad-link": ("Bad Link.md", "---\nsource: generated\n---\n# Bad Link\n\n- [[Missing Note]]\n"),
                "user-overwrite": ("Existing User.md", "---\nsource: generated\n---\n# Existing User\n"),
            }
            for shard_id, (name, body) in cases.items():
                scratch = root / shard_id
                draft_dir = scratch / "draft_notes"
                draft_dir.mkdir(parents=True)
                (draft_dir / name).write_text(body, encoding="utf-8")
                inventory["shards"].append({"id": shard_id, "status": "succeeded", "scratch_dir": str(scratch)})

            result = shards.reduce_generation_shards(
                inventory,
                vault_path=vault,
                known_note_titles={"Intelligence Home"},
            )

        statuses = {item["id"]: item["status"] for item in result["shards"]}
        self.assertEqual(statuses["good"], "merged")
        self.assertEqual(statuses["duplicate-a"], "rejected")
        self.assertEqual(statuses["duplicate-b"], "rejected")
        self.assertEqual(statuses["invalid-frontmatter"], "rejected")
        self.assertEqual(statuses["missing-source"], "rejected")
        self.assertEqual(statuses["bad-link"], "rejected")
        self.assertEqual(statuses["user-overwrite"], "rejected")
        self.assertEqual(result["reducer"]["merged_count"], 1)
        self.assertEqual(result["reducer"]["rejected_count"], 6)

    def test_incremental_cache_records_hits_misses_and_rejects_corrupt_cache(self) -> None:
        cache_module = load_module(INCREMENTAL_CACHE_SCRIPT, "incremental_cache_behavior_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "rebuild_cache.json"
            cache = cache_module.load_incremental_cache(cache_path)
            first = cache_module.get_or_build(cache, "support", "a", {"value": 1}, lambda: {"body": "one"})
            second = cache_module.get_or_build(cache, "support", "a", {"value": 1}, lambda: {"body": "two"})
            third = cache_module.get_or_build(cache, "support", "a", {"value": 2}, lambda: {"body": "three"})
            cache_module.write_incremental_cache(cache_path, cache)
            cache_path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(SystemExit):
                cache_module.load_incremental_cache(cache_path)

        self.assertEqual(first.value, {"body": "one"})
        self.assertFalse(first.hit)
        self.assertEqual(second.value, {"body": "one"})
        self.assertTrue(second.hit)
        self.assertEqual(third.value, {"body": "three"})
        self.assertEqual(cache["stats"]["hits"], 1)
        self.assertEqual(cache["stats"]["misses"], 2)

    def test_incremental_cache_invalidates_when_dependencies_change(self) -> None:
        cache_module = load_module(INCREMENTAL_CACHE_SCRIPT, "incremental_cache_dependency_test")
        cache = cache_module.empty_incremental_cache()
        first = cache_module.get_or_build(
            cache,
            "note_render.support",
            "support-a",
            {"body": "same"},
            lambda: "first",
            dependencies={"source": "one"},
        )
        second = cache_module.get_or_build(
            cache,
            "note_render.support",
            "support-a",
            {"body": "same"},
            lambda: "second",
            dependencies={"source": "two"},
        )

        self.assertFalse(first.hit)
        self.assertFalse(second.hit)
        self.assertEqual(second.value, "second")
        self.assertEqual(cache["stats"]["invalidations"]["note_render.support"], 1)
        self.assertIn("note_render.support:support-a", cache["dependency_graph"])

    def test_incremental_cache_write_redacts_sensitive_strings(self) -> None:
        cache_module = load_module(INCREMENTAL_CACHE_SCRIPT, "incremental_cache_sensitive_write_test")
        cache = cache_module.empty_incremental_cache()
        cache_module.get_or_build(
            cache,
            "support",
            "credentialed-note",
            {"value": 1},
            lambda: {
                "body": (
                    "Contact support@example.com, fetch "
                    "https://gitlab+deploy-token-20:secret@gitlab.acme.test/repo.git, "
                    "and rotate sk-proj-testtoken_1234567890abcdef."
                )
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "rebuild_cache.json"
            cache_module.write_incremental_cache(cache_path, cache)
            payload = cache_path.read_text(encoding="utf-8")

        self.assertNotIn("support@example.com", payload)
        self.assertNotIn("gitlab+deploy-token-20:secret@", payload)
        self.assertNotIn("sk-proj-testtoken_1234567890abcdef", payload)
        self.assertIn("[REDACTED_EMAIL]", payload)
        self.assertIn("[REDACTED_CREDENTIALS]@", payload)
        self.assertIn("[REDACTED_API_KEY]", payload)

    def test_rate_limiter_records_backpressure_waits(self) -> None:
        rate_module = load_module(RATE_LIMITS_SCRIPT, "rate_limits_wait_test")
        recorder = rate_module.RateLimitRecorder()
        limiter = rate_module.WindowRateLimiter(
            {
                "openai_requests_per_minute": 1,
                "openai_tokens_per_minute": 100,
                "fail_fast_seconds": 1,
            },
            recorder=recorder,
            window_seconds=0.01,
        )

        limiter.acquire_openai(stage="semantic_embedding", worker_count=8, tokens=1, recommended_knob="embedding_workers")
        limiter.acquire_openai(stage="semantic_embedding", worker_count=8, tokens=1, recommended_knob="embedding_workers")

        events = recorder.events()
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "wait")

    def test_default_rate_limits_use_openai_throughput_upgrade_without_worker_downscaling(self) -> None:
        performance = load_module(GENERATION_PERFORMANCE_SCRIPT, "generation_performance_defaults_test")

        rate_config = performance.default_rate_limit_config({})
        generation_config = performance.default_generation_config({})

        self.assertEqual(rate_config["openai_requests_per_minute"], 3000)
        self.assertEqual(rate_config["openai_tokens_per_minute"], 3000000)
        self.assertEqual(rate_config["retry_attempts"], 6)
        self.assertEqual(rate_config["retry_max_seconds"], 90.0)
        self.assertEqual(generation_config["embedding_workers"], 8)
        self.assertEqual(generation_config["llm_synthesis_workers"], 10)
        self.assertEqual(generation_config["agent_shards"]["max_concurrent_shards"], 6)

    def test_hierarchical_reducer_defaults_use_batch_size_eight(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducer_batch_defaults_test")
        profile_module = load_module(INIT_INTELLIGENCE_PROFILE_SCRIPT, "init_profile_batch_defaults_test")

        reducer_config = reducers.default_evidence_scaling_config({})["hierarchical_reducers"]
        profile = profile_module.build_profile()

        self.assertEqual(reducer_config["batch_size"], 8)
        self.assertEqual(profile["evidence_scaling"]["hierarchical_reducers"]["batch_size"], 8)

    def test_hierarchical_reducer_batches_eight_specs_per_gpt_request(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducer_batch_grouping_test")
        specs = [
            {
                "id": f"source-repo-doc-docs-{index:04d}",
                "layer": "source",
                "source_kind": "repo-doc",
                "input_count": 1,
                "cards": [{"id": f"repo-doc:{index}", "source_kind": "repo-doc", "summary": "Product docs."}],
            }
            for index in range(16)
        ]

        class CountingClient(reducers.FixtureHierarchicalReducerClient):
            def __init__(self) -> None:
                super().__init__()
                self.batch_sizes: list[int] = []

            def reduce_many(self, specs, *, model, reasoning_effort, worker_count):  # type: ignore[no-untyped-def]
                self.batch_sizes.append(len(specs))
                return super().reduce_many(specs, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)

        client = CountingClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            event_recorder = reducers.ReducerEventRecorder(Path(tmp_dir), enabled=True)
            _results, stats = reducers._run_layer(
                layer="source_shards",
                specs=specs,
                cache=None,
                client=client,
                model="gpt-5.5",
                reasoning_effort="medium",
                worker_count=1,
                force=False,
                progress_callback=None,
                batch_size=8,
                split_on_timeout=True,
                event_recorder=event_recorder,
            )

        self.assertEqual(client.batch_sizes, [8, 8])
        self.assertEqual(stats["effective_batch_sizes"], {"8": 2})
        self.assertEqual(stats["gpt_call_count"], 2)
        self.assertEqual(stats["gpt_call_count_saved_vs_batch_size_4"], 2)

    def test_hierarchical_reducer_split_retry_reports_timeout_metrics(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducer_split_metrics_test")
        specs = [
            {
                "id": f"source-wiki-page-{index:04d}",
                "layer": "source",
                "source_kind": "wiki-page",
                "input_count": 1,
                "cards": [{"id": f"wiki:{index}", "source_kind": "wiki-page", "summary": "Workflow docs."}],
            }
            for index in range(3)
        ]

        class FlakyBatchClient(reducers.FixtureHierarchicalReducerClient):
            def __init__(self) -> None:
                super().__init__()
                self.batch_sizes: list[int] = []

            def reduce_many(self, specs, *, model, reasoning_effort, worker_count):  # type: ignore[no-untyped-def]
                self.batch_sizes.append(len(specs))
                if len(specs) > 1:
                    raise TimeoutError("reducer timed out")
                return super().reduce_many(specs, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)

        client = FlakyBatchClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            event_recorder = reducers.ReducerEventRecorder(Path(tmp_dir), enabled=True)
            _results, stats = reducers._run_layer(
                layer="source_shards",
                specs=specs,
                cache=None,
                client=client,
                model="gpt-5.5",
                reasoning_effort="medium",
                worker_count=1,
                force=False,
                progress_callback=None,
                batch_size=8,
                split_on_timeout=True,
                event_recorder=event_recorder,
            )

        self.assertEqual(client.batch_sizes, [3, 1, 1, 1])
        self.assertEqual(stats["split_count"], 1)
        self.assertEqual(stats["timeout_count"], 1)
        self.assertEqual(stats["effective_batch_sizes"], {"1": 3, "3": 1})
        self.assertEqual(stats["gpt_call_count"], 4)

    def test_reducer_concurrency_recommendation_uses_provider_headroom_and_latency(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducer_recommendation_test")
        batch_metrics = {
            "split_count": 0,
            "timeout_count": 0,
            "malformed_response_count": 0,
            "p50_elapsed_seconds": 10.0,
            "p95_elapsed_seconds": 20.0,
        }
        reducer_events = [
            {
                "provider_headers": {
                    "limit_requests": 3000,
                    "remaining_requests": 1800,
                    "limit_tokens": 3000000,
                    "remaining_tokens": 1800000,
                }
            }
        ]

        stable = reducers.reducer_concurrency_recommendation(
            current_max_concurrent_openai_reducers=24,
            batch_metrics=batch_metrics,
            reducer_events=reducer_events,
            rate_limit_events=[],
        )
        missing_headers = reducers.reducer_concurrency_recommendation(
            current_max_concurrent_openai_reducers=24,
            batch_metrics=batch_metrics,
            reducer_events=[],
            rate_limit_events=[],
        )
        throttled = reducers.reducer_concurrency_recommendation(
            current_max_concurrent_openai_reducers=24,
            batch_metrics=batch_metrics,
            reducer_events=reducer_events,
            rate_limit_events=[{"event": "provider_retry_after"}],
        )
        split = reducers.reducer_concurrency_recommendation(
            current_max_concurrent_openai_reducers=24,
            batch_metrics={**batch_metrics, "split_count": 1},
            reducer_events=reducer_events,
            rate_limit_events=[],
        )

        self.assertEqual(stable["recommended_max_concurrent_openai_reducers"], 48)
        self.assertEqual(missing_headers["recommended_max_concurrent_openai_reducers"], 24)
        self.assertEqual(throttled["recommended_max_concurrent_openai_reducers"], 24)
        self.assertEqual(split["recommended_max_concurrent_openai_reducers"], 24)

    def test_provider_rate_limit_header_parser_handles_limits_remaining_and_resets(self) -> None:
        rate_module = load_module(RATE_LIMITS_SCRIPT, "rate_limits_header_parse_test")

        observed = rate_module.parse_provider_rate_limit_headers(
            {
                "X-RateLimit-Limit-Requests": "1,500",
                "x-ratelimit-limit-tokens": "2500000",
                "x-ratelimit-remaining-requests": "1499",
                "x-ratelimit-remaining-tokens": "2499000",
                "x-ratelimit-reset-requests": "500ms",
                "x-ratelimit-reset-tokens": "1m30s",
            }
        )

        self.assertEqual(observed["limit_requests"], 1500)
        self.assertEqual(observed["limit_tokens"], 2500000)
        self.assertEqual(observed["remaining_requests"], 1499)
        self.assertEqual(observed["remaining_tokens"], 2499000)
        self.assertEqual(observed["reset_requests_seconds"], 0.5)
        self.assertEqual(observed["reset_tokens_seconds"], 90.0)

    def test_provider_ceiling_lowers_effective_openai_window_and_records_event(self) -> None:
        rate_module = load_module(RATE_LIMITS_SCRIPT, "rate_limits_provider_ceiling_test")
        recorder = rate_module.RateLimitRecorder()
        limiter = rate_module.WindowRateLimiter(
            {
                "openai_requests_per_minute": 3000,
                "openai_tokens_per_minute": 3000000,
                "fail_fast_seconds": 1,
            },
            recorder=recorder,
            window_seconds=0.01,
        )

        limiter.observe_openai_response_headers(
            {
                "x-ratelimit-limit-requests": "1",
                "x-ratelimit-limit-tokens": "100",
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": "10ms",
            },
            stage="semantic_embedding",
            worker_count=8,
            recommended_knob="embedding_workers",
        )
        limiter.acquire_openai(stage="semantic_embedding", worker_count=8, tokens=1, recommended_knob="embedding_workers")
        limiter.acquire_openai(stage="semantic_embedding", worker_count=8, tokens=1, recommended_knob="embedding_workers")

        events = recorder.events()
        self.assertTrue(any(event["event"] == "provider_limits_observed" for event in events))
        ceiling_events = [event for event in events if event["event"] == "provider_ceiling_applied"]
        self.assertEqual(len(ceiling_events), 1)
        self.assertEqual(ceiling_events[0]["effective_openai_requests_per_minute"], 1)
        self.assertEqual(ceiling_events[0]["effective_openai_tokens_per_minute"], 100)
        self.assertTrue(any(event["event"] == "wait" and event["budget_key"] == "openai" for event in events))

    def test_default_retry_budget_uses_six_attempts_and_ninety_second_cap(self) -> None:
        rate_module = load_module(RATE_LIMITS_SCRIPT, "rate_limits_retry_budget_test")
        recorder = rate_module.RateLimitRecorder()
        attempts = 0
        sleeps: list[float] = []

        def action() -> None:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("transient")

        with mock.patch.object(rate_module.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            with self.assertRaises(RuntimeError):
                rate_module.with_retries(
                    action=action,
                    config={"retry_base_seconds": 50.0},
                    recorder=recorder,
                    stage="semantic_embedding",
                    worker_count=8,
                    recommended_knob="embedding_workers",
                )

        self.assertEqual(attempts, 6)
        self.assertEqual(sleeps, [50.0, 90.0, 90.0, 90.0, 90.0])

    def test_successful_openai_clients_record_provider_response_headers(self) -> None:
        semantic = load_module(SEMANTIC_SCRIPT, "semantic_openai_header_observation_test")
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_openai_header_observation_test")
        rate_module = sys.modules["rate_limits"]
        recorder = rate_module.RateLimitRecorder()
        limiter = rate_module.WindowRateLimiter(
            {
                "openai_requests_per_minute": 3000,
                "openai_tokens_per_minute": 3000000,
                "fail_fast_seconds": 1,
            },
            recorder=recorder,
            window_seconds=0.01,
        )

        class FakeResponse:
            def __init__(self, payload: dict) -> None:
                self.payload = payload
                self.headers = {
                    "x-ratelimit-limit-requests": "1500",
                    "x-ratelimit-limit-tokens": "2500000",
                    "x-ratelimit-remaining-requests": "1499",
                    "x-ratelimit-reset-requests": "1s",
                }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return json.dumps(self.payload).encode("utf-8")

        response_payloads: list[dict[str, object]] = []

        def fake_urlopen(request, timeout):
            del timeout
            body = json.loads(request.data.decode("utf-8"))
            if str(request.full_url).endswith("/embeddings"):
                return FakeResponse({"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
            response_payloads.append(body)
            input_text = "\n".join(str(message.get("content", "")) for message in body.get("input", []))
            if "Product BASB shard worker" in input_text:
                return FakeResponse(
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": json.dumps(
                                            {
                                                "notes": [
                                                    {
                                                        "title": "Shard",
                                                        "summary": "Shard summary.",
                                                        "highlights": ["One"],
                                                        "distilled_takeaways": ["Two"],
                                                        "executive_use": "Use.",
                                                        "can_feed": ["Output Pipeline"],
                                                        "evidence_ids": ["card-1"],
                                                    }
                                                ],
                                                "evidence_cards": [],
                                                "shard_insights": [],
                                            }
                                        ),
                                    }
                                ],
                            }
                        ]
                    }
                )
            return FakeResponse(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "theme": "Observed",
                                            "summary": "Observed summary.",
                                            "why_this_cluster_exists": "Headers were observed.",
                                            "merge_split_recommendation": "Keep.",
                                            "output_candidate_rationale": "Use.",
                                            "limitations": [],
                                        }
                                    ),
                                }
                            ],
                        }
                    ]
                }
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cards = [
                {
                    "id": "card-1",
                    "kind": "support",
                    "title": "Login",
                    "summary": "Login access",
                    "capabilities": ["identity"],
                    "evidence_terms": ["auth"],
                    "code_terms": ["session"],
                }
            ]
            config = {
                "embedding_model": "text-embedding-3-small",
                "embedding_batch_size": 512,
                "embedding_workers": 8,
                "llm_model": "gpt-5.5",
                "reasoning_effort": "high",
                "llm_synthesis_workers": 10,
                "retry_attempts": 1,
                "retry_base_seconds": 0.01,
                "retry_max_seconds": 0.01,
            }
            shard_spec = {
                "id": "shard-01",
                "kind": "support-evidence",
                "model": "gpt-5.5",
                "reasoning_effort": "high",
                "cards": cards,
                "input_card_count": 1,
                "max_concurrent_shards": 6,
            }

            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                semantic.urllib.request,
                "urlopen",
                side_effect=fake_urlopen,
            ):
                semantic.embed_cards(cards, config, root / "embedding_cache.json", limiter=limiter)
                semantic.synthesize_clusters_with_llm(
                    [
                        {
                            "id": "cluster-1",
                            "theme": "Identity",
                            "cards": cards,
                            "card_ids": ["card-1"],
                        }
                    ],
                    config,
                    root / "llm_cache.json",
                    limiter=limiter,
                )
                shards.llm_shard_worker(
                    shard_spec,
                    root / "shard",
                    limiter=limiter,
                    rate_config=config,
                )

        observed_events = [event for event in recorder.events() if event["event"] == "provider_limits_observed"]
        self.assertEqual([payload["model"] for payload in response_payloads], ["gpt-5.5", "gpt-5.5"])
        self.assertEqual([payload["reasoning"]["effort"] for payload in response_payloads], ["high", "high"])
        self.assertEqual(
            [event["stage"] for event in observed_events],
            ["semantic_embedding", "semantic_llm_synthesis", "generation_shards"],
        )

    def test_business_value_client_retries_timeout_and_uses_configured_timeout(self) -> None:
        rebuild = load_module(REBUILD_PRODUCT_BRAIN_SCRIPT, "business_value_timeout_retry_test")
        attempts: list[float] = []

        class FakeResponse:
            headers = {"x-ratelimit-limit-requests": "3000", "x-ratelimit-limit-tokens": "3000000"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": json.dumps({"business_value": "Retryable synthesis succeeded."}),
                                    }
                                ],
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(_request, timeout):
            attempts.append(timeout)
            if len(attempts) == 1:
                raise TimeoutError("timed out")
            return FakeResponse()

        with mock.patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "PRODUCT_BASB_OPENAI_TIMEOUT_SECONDS": "240",
                "PRODUCT_BASB_RATE_LIMIT_RETRY_BASE_SECONDS": "0.001",
                "PRODUCT_BASB_RATE_LIMIT_RETRY_MAX_SECONDS": "0.001",
            },
        ), mock.patch.object(rebuild.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = rebuild.OpenAIBusinessValueClient().synthesize(
                "capability",
                {"evidence_cards": []},
                "gpt-5.5",
                "high",
            )

        self.assertEqual(result["business_value"], "Retryable synthesis succeeded.")
        self.assertEqual(attempts, [240.0, 240.0])

    def test_openai_request_helper_uses_certifi_when_default_ca_is_missing(self) -> None:
        helper = load_module(OPENAI_REQUESTS_SCRIPT, "openai_requests_certifi_test")
        contexts: list[object] = []

        class FakeDefaultPaths:
            cafile = "/missing/default.pem"
            openssl_cafile = "/missing/openssl.pem"

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def fake_context(*, cafile=None):
            contexts.append(cafile)
            return {"cafile": cafile}

        def fake_opener(request, timeout, context=None):
            del request, timeout
            contexts.append(context)
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            certifi_path = Path(tmp_dir) / "cacert.pem"
            certifi_path.write_text("test certificate bundle", encoding="utf-8")
            request = helper.urllib.request.Request("https://api.openai.test/v1/responses")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(
                helper.ssl,
                "get_default_verify_paths",
                return_value=FakeDefaultPaths(),
            ), mock.patch.object(
                helper.ssl,
                "create_default_context",
                side_effect=fake_context,
            ), mock.patch.object(helper.certifi, "where", return_value=str(certifi_path)):
                with helper.urlopen(request, timeout=10, opener=fake_opener):
                    pass

        self.assertEqual(contexts[0], str(certifi_path))
        self.assertEqual(contexts[1], {"cafile": str(certifi_path)})

    def test_openai_request_helper_prefers_certifi_over_default_ca(self) -> None:
        helper = load_module(OPENAI_REQUESTS_SCRIPT, "openai_requests_certifi_preference_test")
        contexts: list[object] = []

        class FakeDefaultPaths:
            cafile = ""
            openssl_cafile = ""

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def fake_context(*, cafile=None):
            contexts.append(cafile)
            return {"cafile": cafile}

        def fake_opener(request, timeout, context=None):
            del request, timeout
            contexts.append(context)
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            certifi_path = Path(tmp_dir) / "certifi.pem"
            default_path = Path(tmp_dir) / "default.pem"
            certifi_path.write_text("certifi certificate bundle", encoding="utf-8")
            default_path.write_text("default certificate bundle", encoding="utf-8")
            FakeDefaultPaths.cafile = str(default_path)
            request = helper.urllib.request.Request("https://api.openai.test/v1/responses")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(
                helper.ssl,
                "get_default_verify_paths",
                return_value=FakeDefaultPaths(),
            ), mock.patch.object(
                helper.ssl,
                "create_default_context",
                side_effect=fake_context,
            ), mock.patch.object(helper.certifi, "where", return_value=str(certifi_path)):
                with helper.urlopen(request, timeout=10, opener=fake_opener):
                    pass

        self.assertEqual(contexts[0], str(certifi_path))
        self.assertEqual(contexts[1], {"cafile": str(certifi_path)})

    def test_business_value_defaults_use_medium_entities_and_high_ontology_reasoning(self) -> None:
        rebuild = load_module(REBUILD_PRODUCT_BRAIN_SCRIPT, "business_value_reasoning_defaults_test")

        config = rebuild.default_business_value_config({})

        self.assertEqual(config["reasoning_effort"], "medium")
        self.assertEqual(config["ontology_reasoning_effort"], "high")
        self.assertEqual(rebuild.business_value_task_config(config, "capability")["reasoning_effort"], "medium")
        self.assertEqual(rebuild.business_value_task_config(config, "product_ontology")["reasoning_effort"], "high")
        self.assertEqual(rebuild.business_value_task_config(config, "product_ontology_repair")["reasoning_effort"], "high")

    def test_business_value_synthesis_batches_misses_and_reuses_cache(self) -> None:
        rebuild = load_module(REBUILD_PRODUCT_BRAIN_SCRIPT, "business_value_batch_cache_test")
        cache = rebuild.incremental_cache.empty_incremental_cache()
        calls: list[tuple[str, list[str]]] = []

        class FakeClient:
            def synthesize_batch(self, task, items, model, reasoning_effort):
                calls.append((task, [item["id"] for item in items]))
                return {
                    "items": [
                        {
                            "id": item["id"],
                            "target_persona": "Product teams",
                            "user_problem": f"Need {item['id']} translated into action.",
                            "business_value": f"Business value for {item['id']}.",
                            "success_metric": ["Metric A", "Metric B"],
                            "value_score": 8,
                            "evidence_confidence": {"level": "medium", "rationale": "Fixture evidence."},
                            "implementation_leverage": "Use linked evidence.",
                        }
                        for item in items
                    ]
                }

        config = {
            **rebuild.default_business_value_config({}),
            "batch_size": 2,
            "synthesis_workers": 24,
            "cache_enabled": True,
            "max_repair_attempts": 1,
        }
        task_items = {
            "capability": [
                {"id": "cap-1", "payload": {"title": "One"}},
                {"id": "cap-2", "payload": {"title": "Two"}},
                {"id": "cap-3", "payload": {"title": "Three"}},
            ]
        }

        first = rebuild.synthesize_business_value_entities(task_items, cache=cache, config=config, client=FakeClient())
        second = rebuild.synthesize_business_value_entities(task_items, cache=cache, config=config, client=FakeClient())

        self.assertEqual(calls, [("capability", ["cap-1", "cap-2"]), ("capability", ["cap-3"])])
        self.assertEqual(first.values["capability"]["cap-1"]["success_metric"], "Metric A; Metric B")
        self.assertEqual(first.inventory["cache_hits"], 0)
        self.assertEqual(first.inventory["cache_misses"], 3)
        self.assertEqual(first.inventory["batch_count"], 2)
        self.assertEqual(first.inventory["gpt_call_count"], 2)
        self.assertEqual(second.inventory["cache_hits"], 3)

    def test_business_value_cache_key_ignores_volatile_generation_fields(self) -> None:
        rebuild = load_module(REBUILD_PRODUCT_BRAIN_SCRIPT, "business_value_stable_payload_test")
        config = {
            **rebuild.default_business_value_config({}),
            "cache_enabled": True,
        }
        first_payload = {
            "title": "Workspace Intelligence",
            "generated_at": "2026-05-10",
            "run_id": "job-1",
            "scratch_dir": "/tmp/job-1/shard-01",
            "shard_insight_links": ["[[Generation Shard - shard-01]]"],
            "evidence_cards": [
                {"id": "card-b", "source_kind": "repo-doc", "summary": "Product docs describe the workflow."},
                {"id": "card-a", "source_kind": "support-article", "summary": "Support docs describe the workflow."},
            ],
        }
        second_payload = {
            "title": "Workspace Intelligence",
            "generated_at": "2026-05-11",
            "run_id": "job-2",
            "scratch_dir": "/tmp/job-2/shard-99",
            "shard_insight_links": ["[[Generation Shard - shard-99]]"],
            "evidence_cards": [
                {"id": "card-a", "source_kind": "support-article", "summary": "Support docs describe the workflow."},
                {"id": "card-b", "source_kind": "repo-doc", "summary": "Product docs describe the workflow."},
            ],
        }

        self.assertEqual(
            rebuild.business_value_cache_key("packet", "workspace-intelligence", first_payload, config),
            rebuild.business_value_cache_key("packet", "workspace-intelligence", second_payload, config),
        )

    def test_business_value_inventory_reports_cache_miss_reasons_and_warm_ratio(self) -> None:
        rebuild = load_module(REBUILD_PRODUCT_BRAIN_SCRIPT, "business_value_cache_miss_reason_test")
        cache = rebuild.incremental_cache.empty_incremental_cache()

        class FakeClient:
            def synthesize_batch(self, task, items, model, reasoning_effort):
                del task, model, reasoning_effort
                return {
                    "items": [
                        {
                            "id": item["id"],
                            "target_persona": "Product teams",
                            "user_problem": f"Problem for {item['payload']['title']}",
                            "business_value": f"Value for {item['payload']['title']}",
                            "success_metric": "Metric",
                            "value_score": 8,
                            "evidence_confidence": "medium",
                            "implementation_leverage": "Use linked evidence.",
                        }
                        for item in items
                    ]
                }

        config = {**rebuild.default_business_value_config({}), "cache_enabled": True, "batch_size": 4}
        first = {"capability": [{"id": "capability-a", "payload": {"title": "Alpha"}}]}
        changed = {"capability": [{"id": "capability-a", "payload": {"title": "Alpha changed"}}]}

        rebuild.synthesize_business_value_entities(first, cache=cache, config=config, client=FakeClient())
        second = rebuild.synthesize_business_value_entities(changed, cache=cache, config=config, client=FakeClient())

        self.assertEqual(second.inventory["cache_misses"], 1)
        self.assertEqual(second.inventory["warm_cache_hit_ratio"], 0.0)
        self.assertIn("capability", second.inventory["cache_miss_reasons"])
        self.assertIn("payload_changed", second.inventory["cache_miss_reasons"]["capability"])

    def test_business_value_synthesis_repairs_malformed_batch_by_splitting_items(self) -> None:
        rebuild = load_module(REBUILD_PRODUCT_BRAIN_SCRIPT, "business_value_batch_repair_test")
        cache = rebuild.incremental_cache.empty_incremental_cache()
        calls: list[list[str]] = []

        class FlakyClient:
            def synthesize_batch(self, task, items, model, reasoning_effort):
                del task, model, reasoning_effort
                ids = [item["id"] for item in items]
                calls.append(ids)
                if len(ids) > 1:
                    return {"items": [{"id": ids[0], "business_value": "missing fields"}]}
                return {
                    "items": [
                        {
                            "id": ids[0],
                            "target_persona": "Product teams",
                            "user_problem": f"Need {ids[0]} translated into action.",
                            "business_value": f"Business value for {ids[0]}.",
                            "success_metric": "Metric",
                            "value_score": 7,
                            "evidence_confidence": "medium",
                            "implementation_leverage": "Use linked evidence.",
                        }
                    ]
                }

        config = {
            **rebuild.default_business_value_config({}),
            "batch_size": 2,
            "synthesis_workers": 24,
            "cache_enabled": True,
            "max_repair_attempts": 1,
        }

        result = rebuild.synthesize_business_value_entities(
            {
                "packet": [
                    {"id": "packet-1", "payload": {"title": "One"}},
                    {"id": "packet-2", "payload": {"title": "Two"}},
                ]
            },
            cache=cache,
            config=config,
            client=FlakyClient(),
        )

        self.assertEqual(calls, [["packet-1", "packet-2"], ["packet-1", "packet-2"], ["packet-1"], ["packet-2"]])
        self.assertEqual(result.values["packet"]["packet-2"]["business_value"], "Business value for packet-2.")
        self.assertEqual(result.inventory["repair_count"], 1)
        self.assertEqual(result.inventory["gpt_call_count"], 4)
        self.assertEqual(result.inventory["failures"], 0)

    def test_retry_after_parser_and_shared_budget_fail_clearly(self) -> None:
        rate_module = load_module(RATE_LIMITS_SCRIPT, "rate_limits_provider_budget_test")
        self.assertEqual(rate_module.parse_retry_after("2"), 2.0)
        with tempfile.TemporaryDirectory() as tmp_dir:
            budget = rate_module.SharedBudget(
                Path(tmp_dir) / "openai_budget.json",
                {"max_openai_requests_per_budget_window": 1},
            )
            budget.acquire(stage="semantic_embedding", worker_count=8, requests=1, recommended_knob="embedding_workers")
            with self.assertRaises(rate_module.RateLimitExceeded):
                budget.acquire(stage="semantic_embedding", worker_count=8, requests=1, recommended_knob="embedding_workers")

    def test_source_index_cache_skips_unchanged_mirrored_url(self) -> None:
        cache_module = load_module(SOURCE_INDEX_CACHE_SCRIPT, "source_index_cache_skip_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            mirror = Path(tmp_dir) / "mirror.md"
            mirror.write_text("# Mirrored\n", encoding="utf-8")
            cache = cache_module.empty_cache()
            hash_value = cache_module.input_hash("https://example.com/docs", ["a.md"], {"policy": "same"})
            cache_module.store(
                cache,
                "https://example.com/docs",
                hash_value,
                {"url": "https://example.com/docs", "domain": "example.com", "status": "mirrored", "mirror_path": str(mirror)},
            )
            hit = cache_module.lookup(cache, "https://example.com/docs", hash_value)

        self.assertIsNotNone(hit)
        self.assertTrue(hit["source_index_skipped"])
        self.assertEqual(cache["stats"]["skipped_sources"], 1)

    def test_generation_progress_writes_snapshot_and_event_log(self) -> None:
        progress_module = load_module(GENERATION_PROGRESS_SCRIPT, "generation_progress_snapshot_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            recorder = progress_module.ProgressRecorder(Path(tmp_dir))
            recorder.record("rebuild", "started")
            recorder.record("rebuild", "completed", output_candidates=2)
            snapshot = json.loads((Path(tmp_dir) / "generation_progress.json").read_text(encoding="utf-8"))
            events = (Path(tmp_dir) / "generation_progress.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(snapshot["current_status"], "completed")
        self.assertEqual(snapshot["event_count"], 2)
        self.assertEqual(len(events), 2)

    def test_generation_progress_tracks_current_run_missing_work(self) -> None:
        progress_module = load_module(GENERATION_PROGRESS_SCRIPT, "generation_progress_v2_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            inventories = Path(tmp_dir)
            recorder = progress_module.ProgressRecorder(inventories, reset=True)
            recorder.start_run(
                "source_index",
                planned_stages=[
                    ("source_index", "Source indexing", 2),
                    ("rebuild", "Vault rebuild", 8),
                ],
            )
            recorder.record("source_index", "completed", completed_units=2, total_units=2)
            continued = progress_module.ProgressRecorder(inventories)
            continued.record("rebuild", "running", completed_units=4, total_units=8)
            snapshot = json.loads((inventories / "generation_progress.json").read_text(encoding="utf-8"))
            events = (inventories / "generation_progress.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["current_stage"], "rebuild")
        self.assertEqual(snapshot["current_status"], "running")
        self.assertEqual(snapshot["completed_units"], 6)
        self.assertEqual(snapshot["total_units"], 10)
        self.assertEqual(snapshot["remaining_units"], 4)
        self.assertEqual(snapshot["progress_percent"], 60)
        self.assertEqual(snapshot["missing_percent"], 40)
        self.assertEqual(snapshot["unit_label"], "current refresh work units")
        self.assertEqual([stage["stage"] for stage in snapshot["stages"]], ["source_index", "rebuild"])
        self.assertEqual(len(events), 3)

    def test_generation_progress_reset_starts_new_current_run(self) -> None:
        progress_module = load_module(GENERATION_PROGRESS_SCRIPT, "generation_progress_reset_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            inventories = Path(tmp_dir)
            first = progress_module.ProgressRecorder(inventories, reset=True)
            first.start_run("source_index", planned_stages=[("source_index", "Source indexing", 1)])
            first.record("source_index", "completed", completed_units=1, total_units=1)

            second = progress_module.ProgressRecorder(inventories, reset=True)
            second.start_run("source_index", planned_stages=[("source_index", "Source indexing", 4)])
            second.record("source_index", "running", completed_units=1, total_units=4)
            snapshot = json.loads((inventories / "generation_progress.json").read_text(encoding="utf-8"))
            events = (inventories / "generation_progress.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(snapshot["completed_units"], 1)
        self.assertEqual(snapshot["total_units"], 4)
        self.assertEqual(snapshot["missing_percent"], 75)
        self.assertEqual(len(events), 2)

    def test_generation_progress_terminal_snapshot_is_not_active_and_running_is_never_100(self) -> None:
        progress_module = load_module(GENERATION_PROGRESS_SCRIPT, "generation_progress_terminal_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            inventories = Path(tmp_dir)
            first = progress_module.ProgressRecorder(inventories, reset=True)
            first.start_run("rebuild", planned_stages=[("rebuild", "Vault rebuild", 1)])
            first.record("rebuild", "completed", completed_units=1, total_units=1)

            continued = progress_module.ProgressRecorder(inventories)
            self.assertFalse(continued.has_active_run())
            continued.start_run("generation_shards", planned_stages=[("generation_shards", "Shard synthesis", 1)])
            continued.record("generation_shards", "running", completed_units=1, total_units=1)
            snapshot = json.loads((inventories / "generation_progress.json").read_text(encoding="utf-8"))

        self.assertEqual(snapshot["current_status"], "running")
        self.assertLess(snapshot["progress_percent"], 100)
        self.assertGreater(snapshot["missing_percent"], 0)
        self.assertGreater(snapshot["remaining_units"], 0)

    def test_generation_progress_does_not_move_backward_when_scope_expands(self) -> None:
        progress_module = load_module(GENERATION_PROGRESS_SCRIPT, "generation_progress_monotonic_scope_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            inventories = Path(tmp_dir)
            recorder = progress_module.ProgressRecorder(inventories, reset=True)
            recorder.start_run("semantic_clustering", planned_stages=[("semantic_clustering", "Semantic clustering", 10)])
            recorder.record("semantic_clustering", "running", completed_units=8, total_units=10)
            first = json.loads((inventories / "generation_progress.json").read_text(encoding="utf-8"))
            recorder.record("semantic_clustering", "running", completed_units=12, total_units=80)
            second = json.loads((inventories / "generation_progress.json").read_text(encoding="utf-8"))

        self.assertGreaterEqual(second["progress_percent"], first["progress_percent"])
        self.assertTrue(second["scope_expanded"])
        self.assertEqual(second["discovered_total_units"], 80)

    def test_source_fetch_progress_callback_tracks_completed_links(self) -> None:
        source_indices = load_module(BUILD_SOURCE_INDICES_SCRIPT, "build_source_indices_progress_test")
        cache_module = load_module(SOURCE_INDEX_CACHE_SCRIPT, "source_index_cache_progress_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            paths = source_indices.Paths(
                workspace=root,
                vault=root / "vault",
                corpus=root / "corpus",
                mirror=root / "mirror",
                docx_extract=root / "docx",
                repos_root=root / "repos",
                links_dir=root / "links",
                json_dir=root / "inventories",
            )
            events: list[dict[str, int]] = []

            def fake_fetch(url, source_refs, links_dir, settings):
                return {
                    "url": url,
                    "domain": "example.com",
                    "source_refs": source_refs,
                    "status": "blocked" if url.endswith("/two") else "mirrored",
                }

            source_cache = cache_module.load_cache(root / "source_index_cache.json")
            settings = {"source_fetch_workers": 2, "source_index_cache": source_cache}
            with mock.patch.object(source_indices, "fetch_url", side_effect=fake_fetch):
                records = source_indices.build_link_inventory(
                    {
                        "https://example.com/one": {"a.md"},
                        "https://example.com/two": {"b.md"},
                    },
                    paths,
                    settings,
                    progress_callback=lambda completed, total: events.append(
                        {"completed": completed, "total": total}
                    ),
                )

        self.assertEqual(len(records), 2)
        self.assertEqual(events[-1], {"completed": 2, "total": 2})
        self.assertIn({"completed": 1, "total": 2}, events)

    def test_benchmark_history_tracks_trends_across_runs(self) -> None:
        benchmark_module = load_module(BENCHMARK_REBUILD_SCRIPT, "benchmark_rebuild_history_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            inventories = Path(tmp_dir)
            first = {
                "label": "test",
                "manifest": "product.yaml",
                "runs": [{"total_seconds": 10.0, "rebuild_seconds": 8.0, "cache_stats": {"hits": 1}}],
                "digest_stable": True,
            }
            second = {
                "label": "test",
                "manifest": "product.yaml",
                "runs": [{"total_seconds": 6.0, "rebuild_seconds": 5.0, "cache_stats": {"hits": 2}}],
                "digest_stable": True,
            }
            benchmark_module.update_history(inventories, first)
            trends = benchmark_module.update_history(inventories, second)

        self.assertEqual(trends["entry_count"], 2)
        self.assertEqual(trends["best_total_seconds"], 6.0)
        self.assertEqual(trends["worst_total_seconds"], 10.0)

    def test_benchmark_markdown_report_is_a_generated_linked_note(self) -> None:
        benchmark_module = load_module(BENCHMARK_REBUILD_SCRIPT, "benchmark_rebuild_markdown_report_test")
        note = benchmark_module.render_report(
            {
                "label": "warm-cache",
                "manifest": "/tmp/manifest.yaml",
                "runs": [{"run": 1, "total_seconds": 4.2, "cache_stats": {"hits": 10, "misses": 0}, "shard_summary": {"merged_count": 2}}],
                "digest_stable": True,
                "history": {"entry_count": 1},
            }
        )

        self.assertTrue(note.startswith("---\ntype: hub\nsource: generated"))
        self.assertIn("[[Intelligence Home]]", note)

    def test_llm_shard_worker_writes_schema_valid_note_metadata(self) -> None:
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_llm_worker_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch = Path(tmp_dir)
            spec = {
                "id": "shard-01",
                "kind": "support-evidence",
                "status": "running",
                "item_count": 2,
                "worker_mode": "fixture",
                "model": "gpt-5.5",
                "reasoning_effort": "high",
                "cards": [
                    {"id": "card-1", "title": "Branding settings", "kind": "support", "summary": "Branding controls."},
                    {"id": "card-2", "title": "Theme docs", "kind": "wiki", "summary": "Theme implementation."},
                ],
                "input_card_count": 2,
                "max_concurrent_shards": 6,
            }
            result = shards.llm_shard_worker(
                spec,
                scratch,
                client=shards.FixtureShardClient(),
                rate_config={"retry_attempts": 1, "retry_base_seconds": 0.01, "retry_max_seconds": 0.01},
            )

            note_path = scratch / "draft_notes" / result["draft_notes"][0]
            body = note_path.read_text(encoding="utf-8")

        self.assertEqual(result["llm_status"], "fixture")
        self.assertEqual(result["input_card_count"], 2)
        self.assertEqual(result["output_note_count"], 1)
        self.assertEqual(result["shard_insight_count"], 1)
        self.assertEqual(result["reasoning_effort"], "high")
        self.assertIn("source: generated", body)
        self.assertIn("basb_stage: distill", body)
        self.assertIn("llm_reasoning_effort: \"high\"", body)
        self.assertIn("## Distilled Takeaways", body)

    def test_reducer_prunes_only_stale_generated_shard_notes(self) -> None:
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_prune_generated_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            shard_dir = vault / "80 Assets" / "Generation Shards"
            shard_dir.mkdir(parents=True)
            stale_generated = shard_dir / "Generation Shard - stale.md"
            stale_generated.write_text("---\ntype: shard-record\nsource: generated\n---\n# Stale\n", encoding="utf-8")
            user_authored = shard_dir / "Generation Shard - user.md"
            user_authored.write_text("---\ntype: shard-record\nsource: manual\n---\n# User\n", encoding="utf-8")
            scratch = root / "scratch" / "shard-01" / "draft_notes"
            scratch.mkdir(parents=True)
            draft = scratch / "Generation Shard - shard-01 - Support.md"
            draft.write_text(
                "---\ntype: shard-record\nsource: generated\n---\n# Support\n\n- [[Intelligence Home]]\n",
                encoding="utf-8",
            )
            inventory = {
                "shards": [
                    {
                        "id": "shard-01",
                        "kind": "support-evidence",
                        "status": "succeeded",
                        "scratch_dir": str(scratch.parent),
                        "draft_notes": [draft.name],
                    }
                ],
                "reducer": {"status": "pending"},
            }

            result = shards.reduce_generation_shards(inventory, vault_path=vault, known_note_titles={"Intelligence Home"})
            self.assertFalse(stale_generated.exists())
            self.assertTrue(user_authored.exists())
            self.assertTrue((shard_dir / draft.name).exists())

        self.assertEqual(result["reducer"]["pruned_generated_note_count"], 1)

    def test_shard_insights_are_collected_for_reducer_inputs(self) -> None:
        shards = load_module(GENERATION_SHARDS_SCRIPT, "generation_shards_insight_collect_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch = Path(tmp_dir) / "shard-01"
            scratch.mkdir()
            (scratch / "shard_insights.json").write_text(
                json.dumps(
                    [
                        {
                            "theme": "Repository ingestion gap",
                            "summary": "The shard identifies the repository but lacks inspectable source artifacts.",
                            "evidence_ids": ["repo-code-1"],
                            "code_surfaces": ["repository:repo"],
                            "output_rationale": "Do not use this as evidence.",
                        },
                        {
                            "theme": "Branding Configuration",
                            "summary": "Branding evidence appears across support and code.",
                            "evidence_ids": ["support:branding"],
                            "code_surfaces": ["app/branding.py"],
                            "output_rationale": "Create a runbook.",
                            "capabilities": ["branding"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            insights = shards.collect_shard_insights(
                {
                    "shards": [
                        {
                            "id": "shard-01",
                            "kind": "support-evidence",
                            "status": "succeeded",
                            "scratch_dir": str(scratch),
                            "draft_notes": ["Generation Shard - shard-01.md"],
                        }
                    ]
                }
            )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0]["theme"], "Branding Configuration")
        self.assertEqual(insights[0]["source_shard_note"], "[[Generation Shard - shard-01]]")

    def test_output_candidate_promotion_preserves_generated_candidate_link(self) -> None:
        promote_module = load_module(PROMOTE_OUTPUT_CANDIDATE_SCRIPT, "promote_output_candidate_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault = Path(tmp_dir) / "vault"
            candidates_dir = vault / "30 Initiatives" / "Output Candidates"
            candidates_dir.mkdir(parents=True)
            candidate = candidates_dir / "Output Candidate - Branding.md"
            candidate.write_text(
                "---\ntype: output\nsource: generated\nstatus: proposed\noutput_kind: spec\n---\n# Branding\n",
                encoding="utf-8",
            )
            result = promote_module.promote(vault, "Output Candidate - Branding", output_kind="runbook", decision="Ready.")
            promoted_path = Path(result["promoted_path"])
            candidate_body = candidate.read_text(encoding="utf-8")
            promoted_exists = promoted_path.exists()

        self.assertTrue(promoted_exists)
        self.assertEqual(result["output_kind"], "runbook")
        self.assertIn("promotion_status: promoted", candidate_body)

    def test_parallel_note_rendering_is_byte_stable_and_uses_worker_count(self) -> None:
        rendering = load_module(NOTE_RENDERING_SCRIPT, "note_rendering_stability_test")
        observed_workers: list[int] = []
        specs = [
            rendering.NoteRenderSpec(
                path=Path(f"{name}.md"),
                cache_namespace="test",
                cache_key=name,
                payload={"name": name},
                renderer=lambda name=name: f"---\nsource: generated\n---\n# {name}\n",
                generated=True,
            )
            for name in ["b", "a", "c"]
        ]
        first = rendering.render_note_specs(specs, cache=None, workers=32, observed_workers=observed_workers)
        second = rendering.render_note_specs(specs, cache=None, workers=32, observed_workers=observed_workers)

        self.assertEqual([item.path.name for item in first], ["a.md", "b.md", "c.md"])
        self.assertEqual([(item.path, item.body) for item in first], [(item.path, item.body) for item in second])
        self.assertEqual(observed_workers, [32, 32])

    def test_code_intelligence_cache_skips_unchanged_files(self) -> None:
        code_intelligence = load_module(CODE_INTELLIGENCE_SCRIPT, "code_intelligence_cache_skip_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "service.py").write_text("def login():\n    return True\n", encoding="utf-8")
            cache_path = root / "inventories" / "rebuild_cache.json"
            first = code_intelligence.analyze_repositories(
                {"repo": repo},
                {"code_intelligence": {"include_git_history": False, "max_files_per_repo": 10}},
                cache_path=cache_path,
            )
            second = code_intelligence.analyze_repositories(
                {"repo": repo},
                {"code_intelligence": {"include_git_history": False, "max_files_per_repo": 10}},
                cache_path=cache_path,
            )

        self.assertEqual(first["summary"]["cache_hits"], 0)
        self.assertGreaterEqual(second["summary"]["cache_hits"], 1)
        self.assertEqual(first["files"], second["files"])

    def test_hierarchical_reducers_create_unbounded_bounded_source_shards(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducers_unbounded_test")
        cache_module = sys.modules["incremental_cache"]
        cards = [
            {
                "id": f"repo-doc:{index:04d}",
                "source_kind": "repo-doc",
                "title": f"Product document {index}",
                "summary": f"Document section {index} explains onboarding workflow value.",
                "source_uri": f"repo/docs/{index:04d}.md",
                "terms": ["onboarding", "workflow"],
            }
            for index in range(130)
        ]
        cards.append(
            {
                "id": "generated-note:ignored",
                "source_kind": "generated-note",
                "title": "Generated packet",
                "summary": "This generated note must not feed upstream synthesis by default.",
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            result = reducers.run_hierarchical_reducers(
                cards=cards,
                capabilities=[{"key": "onboarding", "title": "Onboarding", "keywords": ["onboarding"]}],
                evidence_config={
                    "generated_notes_feed_synthesis": False,
                    "max_cards_per_source_shard": 10,
                    "max_cards_per_theme_shard": 6,
                    "max_theme_summaries_per_capability_shard": 4,
                    "max_capability_summaries_for_ontology": 3,
                    "max_summary_chars": 300,
                    "unlimited_total_shards": True,
                },
                generation_config={
                    "source_shard_workers": 8,
                    "theme_reducer_workers": 4,
                    "capability_reducer_workers": 2,
                    "ontology_reducer_workers": 1,
                    "max_concurrent_openai_reducers": 8,
                },
                business_config={"llm_model": "gpt-5.5", "reasoning_effort": "high"},
                cache=cache_module.empty_incremental_cache(),
                output_dir=output_dir,
                client=reducers.FixtureHierarchicalReducerClient(),
            )
            source_inventory = json.loads((output_dir / "source_shards.json").read_text(encoding="utf-8"))
            evidence_graph = json.loads((output_dir / "evidence_graph.json").read_text(encoding="utf-8"))

        self.assertGreater(len(source_inventory["shards"]), 12)
        self.assertTrue(all(shard["input_count"] <= 10 for shard in source_inventory["shards"]))
        self.assertEqual(evidence_graph["source_card_count"], 130)
        self.assertNotIn("generated-note", evidence_graph["source_kind_counts"])
        self.assertGreater(len(result["ontology_evidence_cards"]), 0)

    def test_hierarchical_reducer_defaults_use_medium_fanout_and_high_final_reasoning(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducers_reasoning_config_test")

        config = reducers.default_evidence_scaling_config({})

        self.assertEqual(config["hierarchical_reducers"]["source_reasoning_effort"], "medium")
        self.assertEqual(config["hierarchical_reducers"]["theme_reasoning_effort"], "medium")
        self.assertEqual(config["hierarchical_reducers"]["capability_reasoning_effort"], "high")
        self.assertEqual(config["hierarchical_reducers"]["ontology_reasoning_effort"], "high")

    def test_hierarchical_reducers_pass_layer_specific_reasoning_effort(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducers_reasoning_runtime_test")
        cache_module = sys.modules["incremental_cache"]

        class RecordingClient(reducers.FixtureHierarchicalReducerClient):
            def __init__(self) -> None:
                super().__init__()
                self.reasoning_by_layer: dict[str, str] = {}

            def reduce_many(self, specs: list[dict[str, object]], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, dict[str, object]]:
                self.reasoning_by_layer[str(specs[0]["layer"])] = reasoning_effort
                return super().reduce_many(specs, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)

        client = RecordingClient()
        cards = [
            {
                "id": f"repo-doc:{index}",
                "source_kind": "repo-doc",
                "title": f"Workspace setup {index}",
                "summary": "Workspace setup documentation explains customer onboarding and source refresh workflows.",
                "source_uri": f"docs/setup-{index}.md",
                "terms": ["workspace", "onboarding"],
            }
            for index in range(5)
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = reducers.run_hierarchical_reducers(
                cards=cards,
                capabilities=[{"key": "workspace-setup", "title": "Workspace setup", "keywords": ["workspace"]}],
                evidence_config=reducers.default_evidence_scaling_config({}),
                generation_config={
                    "source_shard_workers": 4,
                    "theme_reducer_workers": 4,
                    "capability_reducer_workers": 2,
                    "ontology_reducer_workers": 1,
                    "max_concurrent_openai_reducers": 4,
                },
                business_config={"llm_model": "gpt-5.5", "reasoning_effort": "medium", "ontology_reasoning_effort": "high"},
                cache=cache_module.empty_incremental_cache(),
                output_dir=Path(tmp_dir),
                client=client,
            )

        self.assertEqual(client.reasoning_by_layer["source"], "medium")
        self.assertEqual(client.reasoning_by_layer["theme"], "medium")
        self.assertEqual(client.reasoning_by_layer["capability"], "high")
        self.assertEqual(client.reasoning_by_layer["ontology"], "high")
        self.assertEqual(
            result["reasoning_efforts"],
            {
                "source_shards": "medium",
                "theme_reducers": "medium",
                "capability_reducers": "high",
                "ontology_reducer": "high",
            },
        )

    def test_hierarchical_reducers_compact_large_repo_doc_sets_before_source_reducers(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducers_compaction_test")
        cache_module = sys.modules["incremental_cache"]
        cards = [
            {
                "id": f"repo-doc:{index:05d}",
                "source_kind": "repo-doc",
                "title": f"Operations guide {index}",
                "summary": "Operations workflow, customer support value, and product process evidence.",
                "source_uri": f"acme/docs/section-{index % 200:03d}/guide-{index:05d}.md",
                "terms": ["operations", "workflow", "support"],
            }
            for index in range(2000)
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            result = reducers.run_hierarchical_reducers(
                cards=cards,
                capabilities=[{"key": "operations", "title": "Operations", "keywords": ["operations"]}],
                evidence_config={
                    "generated_notes_feed_synthesis": False,
                    "max_cards_per_source_shard": 10,
                    "max_cards_per_theme_shard": 6,
                    "max_theme_summaries_per_capability_shard": 4,
                    "max_capability_summaries_for_ontology": 3,
                    "max_summary_chars": 300,
                    "unlimited_total_shards": True,
                    "evidence_compaction": {
                        "enabled": True,
                        "max_raw_cards_per_source_group": 50,
                        "max_compacted_cards_per_group": 10,
                        "max_reducer_gpt_calls_per_layer_soft": 80,
                    },
                    "hierarchical_reducers": {"batch_size": 4, "split_on_timeout": True, "live_events_enabled": True},
                },
                generation_config={
                    "source_shard_workers": 8,
                    "theme_reducer_workers": 4,
                    "capability_reducer_workers": 2,
                    "ontology_reducer_workers": 1,
                    "max_concurrent_openai_reducers": 8,
                },
                business_config={"llm_model": "gpt-5.5", "reasoning_effort": "high"},
                cache=cache_module.empty_incremental_cache(),
                output_dir=output_dir,
                client=reducers.FixtureHierarchicalReducerClient(),
            )
            compaction = json.loads((output_dir / "source_compaction.json").read_text(encoding="utf-8"))
            source_inventory = json.loads((output_dir / "source_shards.json").read_text(encoding="utf-8"))

        self.assertEqual(compaction["raw_card_count"], 2000)
        self.assertLessEqual(compaction["compacted_card_count"], 10)
        self.assertLessEqual(compaction["estimated_source_reducer_calls"], 80)
        self.assertLessEqual(len(source_inventory["shards"]), 80)
        self.assertLess(result["gpt_call_count"], 80)

    def test_hierarchical_reducer_cache_reuses_unchanged_layers(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducers_cache_test")
        cache_module = sys.modules["incremental_cache"]

        class CountingClient(reducers.FixtureHierarchicalReducerClient):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0
                self.batch_calls = 0

            def reduce(self, spec: dict[str, object], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, object]:
                self.calls += 1
                return super().reduce(spec, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)

            def reduce_many(self, specs: list[dict[str, object]], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, dict[str, object]]:
                self.batch_calls += 1
                return super().reduce_many(specs, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)

        client = CountingClient()
        cache = cache_module.empty_incremental_cache()
        cards = [
            {
                "id": f"support:{index}",
                "source_kind": "support-article",
                "title": f"Branding support article {index}",
                "summary": "Branding setup helps admins launch branded customer programs.",
                "source_uri": f"https://support.example.test/article/{index}",
                "terms": ["branding"],
            }
            for index in range(24)
        ]
        config = {
            "generated_notes_feed_synthesis": False,
            "max_cards_per_source_shard": 8,
            "max_cards_per_theme_shard": 4,
            "max_theme_summaries_per_capability_shard": 3,
            "max_capability_summaries_for_ontology": 3,
            "max_summary_chars": 300,
            "unlimited_total_shards": True,
        }
        generation_config = {
            "source_shard_workers": 4,
            "theme_reducer_workers": 4,
            "capability_reducer_workers": 2,
            "ontology_reducer_workers": 1,
            "max_concurrent_openai_reducers": 4,
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            first = reducers.run_hierarchical_reducers(
                cards=cards,
                capabilities=[{"key": "branding", "title": "Branding", "keywords": ["branding"]}],
                evidence_config=config,
                generation_config=generation_config,
                business_config={"llm_model": "gpt-5.5", "reasoning_effort": "high"},
                cache=cache,
                output_dir=Path(tmp_dir) / "first",
                client=client,
            )
            calls_after_first = client.calls
            batch_calls_after_first = client.batch_calls
            second = reducers.run_hierarchical_reducers(
                cards=cards,
                capabilities=[{"key": "branding", "title": "Branding", "keywords": ["branding"]}],
                evidence_config=config,
                generation_config=generation_config,
                business_config={"llm_model": "gpt-5.5", "reasoning_effort": "high"},
                cache=cache,
                output_dir=Path(tmp_dir) / "second",
                client=client,
            )

        self.assertGreater(calls_after_first, 0)
        self.assertEqual(client.calls, calls_after_first)
        self.assertEqual(client.batch_calls, batch_calls_after_first)
        self.assertEqual(first["gpt_call_count"], batch_calls_after_first)
        self.assertEqual(second["gpt_call_count"], 0)
        self.assertGreater(second["cache_hits"], 0)

    def test_hierarchical_reducer_partial_source_failure_records_coverage_limitation(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducers_partial_test")
        cache_module = sys.modules["incremental_cache"]

        class OneShardFailureClient(reducers.FixtureHierarchicalReducerClient):
            def reduce(self, spec: dict[str, object], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, object]:
                if spec.get("layer") == "source" and str(spec.get("id", "")).endswith("0001"):
                    raise RuntimeError("source timeout")
                return super().reduce(spec, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)

        cards = [
            {
                "id": f"wiki:{index}",
                "source_kind": "wiki-page",
                "title": f"Workflow page {index}",
                "summary": "The workflow page describes customer-facing rollout steps.",
                "source_uri": f"wiki/{index}.md",
                "terms": ["workflow"],
            }
            for index in range(6)
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = reducers.run_hierarchical_reducers(
                cards=cards,
                capabilities=[{"key": "workflow", "title": "Workflow", "keywords": ["workflow"]}],
                evidence_config={
                    "generated_notes_feed_synthesis": False,
                    "max_cards_per_source_shard": 2,
                    "max_cards_per_theme_shard": 3,
                    "max_theme_summaries_per_capability_shard": 3,
                    "max_capability_summaries_for_ontology": 3,
                    "max_summary_chars": 300,
                    "unlimited_total_shards": True,
                },
                generation_config={
                    "source_shard_workers": 3,
                    "theme_reducer_workers": 2,
                    "capability_reducer_workers": 1,
                    "ontology_reducer_workers": 1,
                    "max_concurrent_openai_reducers": 3,
                },
                business_config={"llm_model": "gpt-5.5", "reasoning_effort": "high"},
                cache=cache_module.empty_incremental_cache(),
                output_dir=Path(tmp_dir),
                client=OneShardFailureClient(),
            )

        self.assertEqual(result["partial_count"], 1)
        self.assertEqual(result["coverage_limitations"][0]["layer"], "source")
        self.assertIn("source timeout", result["coverage_limitations"][0]["reason"])
        self.assertGreater(len(result["ontology_evidence_cards"]), 0)

    def test_openai_hierarchical_reducer_maps_single_item_without_id_to_requested_shard(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducers_single_missing_id_test")

        class FakeResponse:
            headers: dict[str, str] = {}

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "output_text": json.dumps(
                            {
                                "items": [
                                    {
                                        "theme": "AdvocateHub code shard",
                                        "summary": "The reducer summarized the requested shard but omitted its id.",
                                        "source_kind_counts": {"repo-code": 1},
                                        "evidence_ids": ["code:one"],
                                        "confidence": "medium",
                                        "business_value": "Useful code intelligence.",
                                        "workflow_candidates": ["runtime"],
                                        "capability_candidates": ["runtime"],
                                        "risks": [],
                                        "limitations": [],
                                        "code_surfaces": ["apps/hub/app/models/user.rb"],
                                    },
                                    {
                                        "theme": "Extra diagnostic item",
                                        "summary": "The model included an extra unkeyed item.",
                                        "source_kind_counts": {"repo-code": 1},
                                        "evidence_ids": ["code:one"],
                                        "confidence": "low",
                                        "business_value": "Diagnostic.",
                                        "workflow_candidates": [],
                                        "capability_candidates": [],
                                        "risks": [],
                                        "limitations": ["Extra item."],
                                        "code_surfaces": [],
                                    }
                                ]
                            }
                        )
                    }
                ).encode("utf-8")

        def fake_urlopen(*_args: object, **_kwargs: object) -> FakeResponse:
            return FakeResponse()

        original_urlopen = reducers.openai_requests.urlopen
        reducers.openai_requests.urlopen = fake_urlopen
        try:
            client = reducers.OpenAIHierarchicalReducerClient(api_key="test-key")
            result = client.reduce_many(
                [
                    {
                        "id": "source-repo-code-influitive-advocatehub-influitive-0001",
                        "layer": "source",
                        "source_kind": "repo-code",
                        "cards": [{"id": "code:one", "source_kind": "repo-code", "summary": "Code card."}],
                    }
                ],
                model="gpt-5.5",
                reasoning_effort="high",
                worker_count=1,
            )
        finally:
            reducers.openai_requests.urlopen = original_urlopen

        expected_id = "source-repo-code-influitive-advocatehub-influitive-0001"
        self.assertIn(expected_id, result)
        self.assertEqual(result[expected_id]["id"], expected_id)
        self.assertEqual(result[expected_id]["theme"], "AdvocateHub code shard")

    def test_stable_business_payload_excludes_generated_notes_from_upstream_keys(self) -> None:
        evidence = load_module(EVIDENCE_CARDS_SCRIPT, "evidence_cards_generated_cache_key_test")
        base_payload = {
            "evidence_cards": [
                {"id": "repo-doc:1", "source_kind": "repo-doc", "title": "Plan", "summary": "Business plan"},
                {"id": "generated-note:1", "source_kind": "generated-note", "title": "Packet", "summary": "Old generated text"},
            ],
            "run_id": "first",
            "generated_output_candidates": ["[[Candidate A]]"],
        }
        changed_generated_note = {
            **base_payload,
            "evidence_cards": [
                {"id": "repo-doc:1", "source_kind": "repo-doc", "title": "Plan", "summary": "Business plan"},
                {"id": "generated-note:1", "source_kind": "generated-note", "title": "Packet", "summary": "New generated text"},
            ],
            "run_id": "second",
        }
        enabled_payload = {**base_payload, "generated_notes_feed_synthesis": True}
        enabled_changed = {**changed_generated_note, "generated_notes_feed_synthesis": True}

        self.assertEqual(evidence.stable_business_payload(base_payload), evidence.stable_business_payload(changed_generated_note))
        self.assertNotEqual(evidence.stable_business_payload(enabled_payload), evidence.stable_business_payload(enabled_changed))
        self.assertNotEqual(
            evidence.stable_business_payload(
                {
                    "evidence_cards": [
                        {"id": "reducer-summary:1", "source_kind": "reducer-summary", "title": "Theme", "summary": "Old theme"}
                    ]
                }
            ),
            evidence.stable_business_payload(
                {
                    "evidence_cards": [
                        {"id": "reducer-summary:1", "source_kind": "reducer-summary", "title": "Theme", "summary": "New theme"}
                    ]
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
