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
PROMOTE_OUTPUT_CANDIDATE_SCRIPT = TOOLS_DIR / "promote_output_candidate.py"
BENCHMARK_REBUILD_SCRIPT = TOOLS_DIR / "benchmark_rebuild.py"
BUILD_SOURCE_INDICES_SCRIPT = TOOLS_DIR / "build_source_indices.py"
SEMANTIC_SCRIPT = TOOLS_DIR / "semantic_clustering.py"
EVIDENCE_INDEX_SCRIPT = TOOLS_DIR / "evidence_index.py"
EVIDENCE_CARDS_SCRIPT = TOOLS_DIR / "evidence_cards.py"
HIERARCHICAL_REDUCERS_SCRIPT = TOOLS_DIR / "hierarchical_reducers.py"
REBUILD_PRODUCT_BRAIN_SCRIPT = TOOLS_DIR / "rebuild_product_brain.py"


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HighConcurrencyGenerationTests(unittest.TestCase):
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
        self.assertEqual(manifest["schema_version"], 1)
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
                note_rendering.RenderedNote(stale, "# Stale\n", False, False, "support", "stale"),
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

    def test_hierarchical_reducer_cache_reuses_unchanged_layers(self) -> None:
        reducers = load_module(HIERARCHICAL_REDUCERS_SCRIPT, "hierarchical_reducers_cache_test")
        cache_module = sys.modules["incremental_cache"]

        class CountingClient(reducers.FixtureHierarchicalReducerClient):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def reduce(self, spec: dict[str, object], *, model: str, reasoning_effort: str, worker_count: int) -> dict[str, object]:
                self.calls += 1
                return super().reduce(spec, model=model, reasoning_effort=reasoning_effort, worker_count=worker_count)

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
        self.assertEqual(first["gpt_call_count"], calls_after_first)
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
