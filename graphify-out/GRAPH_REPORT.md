# Graph Report - .  (2026-08-06)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 6590 nodes · 12486 edges · 334 communities (273 shown, 61 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 1183 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f8654614`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_session_watcher.py
- patch
- FakeCloudClient
- session_watcher.py
- test_conflict_detector.py
- test_synthetic_pattern_monitor.py
- test_duplicate_merger.py
- TestClaudeCodePluginProvidesHooks
- test_cloud_enablement.py
- test_cli_adapter.py
- test_cloud_bundle.py
- test_whisper_out.py
- routes_admin.py
- IngestSpool
- keys.py
- test_ingest_extraction.py
- test_memory_engine.py
- CloudClient
- test_consolidator.py
- routes_account.py
- IndexBuilder
- test_merge_undo.py
- auto_linker.py
- _make_node_dict
- test_seq_fingerprint.py
- test_cloud_keys.py
- test_eval_whisper/test_metrics.py
- CloudProtectionService
- _settings
- test_feedback_schema.py
- test_config.py
- test_routes.py
- test_pair_batch.py
- TestSubmitFeedbackBasic
- TestSafeBoundary
- test_forgetting_manager.py
- test_hippocampus.py
- _make_vec
- test_cleanup_auto_ingested.py
- test_cloud_client.py
- test_mutation_stamping.py
- test_spreading_activation.py
- test_importance_scorer.py
- TestOutputFunctions
- test_server_manager.py
- test_hybrid_search.py
- ControlledEncoder
- test_protection_routes.py
- _insert_injected_whisper_log
- test_main_lifespan_shutdown.py
- test_backup.py
- test_claude_cli_adapter.py
- test_job_tracker.py
- _make_titled_hybrid
- test_whisper_context.py
- _write_jsonl
- MemoryEngine
- test_stats.py
- _NeverEofProc
- test_adapters.py
- test_self_node.py
- ._builder
- TestSyntheticPromptEndpoint
- TestValidateCase
- TestTimeExtraction
- test_main_backfill_fallback.py
- FakeCloudClient
- test_run_stats.py
- test_cli_cloud_backup.py
- test_relevance_runner.py
- test_parser.py
- conftest.py
- test_auto_linker.py
- test_ingest.py
- test_temporal_search.py
- _insert_node
- _make_node
- TestReleaseVersionVerification
- _create_pair
- _reset_adapter
- test_cloud_cli.py
- _run_fusion
- TestWhisperTopicShift
- test_init_vec_table_guard.py
- test_whisper_health.py
- integration
- test_decay_manager.py
- test_session_watcher_flush.py
- test_backfill_embeddings.py
- test_whisper_claims_investigation.py
- Settings
- test_auto_cluster.py
- _edges_between
- test_llm_cancel.py
- FakeClient
- _make_node
- _candidate
- TestWhisperIntentAware
- test_entitlements.py
- test_migrations.py
- test_llm_json.py
- TestClient
- test_llm_client.py
- test_reuse_stored_vectors.py
- TestMatchSyntheticPattern
- test_miner.py
- test_graph.py
- Database
- test_llm_adapters.py
- test_audit_log.py
- TestWhisperContextBuffer
- TestWhisperRerankerBlendIntegration
- TestEvalWhisperCLI
- test_builder.py
- test_setup_json.py
- test_markdown.py
- test_space_normalization.py
- FakeProtectionService
- test_routes_admin_run_task.py
- test_conflict_claims_investigation.py
- TestMarkOutdated
- FakeEncoder
- TestSeedCase
- _FakeEngine
- TestConfigureLlm
- TestClaudeCodeWirePluginGuard
- TestShouldRewind
- test_mcp_adapter.py
- MemoryEngine
- TestRecallFloorAndSpaceOrdering
- TestWhisperDebugMode
- TestStopOffsetCeiling
- ProtectionOperationCoordinator
- test_embed_node_rows.py
- TestStripTemporalPhrases
- test_eval_recall/test_report.py
- _make_eval_result
- TestClaudeCodeIsWired
- test_file_cache.py
- test_file_store.py
- test_local_auth.py
- test_llm_normalize.py
- test_cloud_crypto.py
- test_cloud_store_lock.py
- setup.py
- TestExtractionSchema
- TestWhisperDecisions
- test_eval_recall/test_seeder.py
- test_proposal_claims_investigation.py
- llm_client.py
- TestMergeHooks
- settings
- test_admin_embedding_backfill_task.py
- _FakeProc
- test_ingest_provider.py
- test_watermark.py
- test_hybrid_search_raw_cosine.py
- GraphIndex
- test_archived_at.py
- TestWhisperFailSilently
- test_eval_recall/test_runner.py
- test_logging.py
- _monkeypatch_run_embedding_backfill
- TestRemoveClaudeHooks
- _write_turns
- test_cloud_settings.py
- FileStore
- test_delete_guarded.py
- _FlakyEncoder
- TestExplorationCEGate
- test_eval_recall/test_corpus.py
- test_db_concurrency.py
- TestRemoveMcpFromJson
- run.sh
- _RecordingDB
- test_embedding_backfill.py
- test_legacy_backfill.py
- _FakeConn
- _FakeEngine
- test_whisper_log_cleanup.py
- server_manager.py
- Path
- TestIngestConfidence
- test_recall_concurrency.py
- TestAggregate
- test_main.py
- TestIsOrmahHook
- cli_adapter.py
- backup.py
- _tool_heavy_turns
- memory_engine.py
- TestSessionBufferRoute
- test_migration_seq.py
- _CancellableEngine
- test_soft_delete_tombstone.py
- SessionHandler
- test_tool_schemas.py
- scheduler.py
- test_scheduler_embedding_backfill.py
- test_conflict_edge_and_confidence_survive_full_rebuild
- test_embedding_observability.py
- mock_hybrid
- main.py
- test_prompt_classifier.py
- test_real_claude_json_schema_recovers_prose_json_fallback
- test_scheduler.py
- test_ingest_session_drain_continuation_self_triggers
- TestCommitStateMonotonic
- test_cloud_transfer.py
- routes_agent.py
- test_tier_manager.py
- mcp_adapter.py
- _reset_deprecation_warn_once
- _no_default_acceptance_roots
- _insert_node
- test_test_safety.py
- test_invalid_llm_output_records_error_not_none
- routes_protection.py
- test_run_survives_an_edge_apply_failure
- test_a_failing_pair_does_not_block_progress_on_earlier_nodes
- test_generate_respects_timeout_hint
- test_cleanup_persisted_stub_never_globs
- test_cancel_set_raises_even_when_child_exits_cleanly
- test_llm_generate_swallows_cancel_and_timeout
- VectorStore
- test_deprecated_key_scanner_warns_once_on_unreadable_source
- test_genuinely_unreadable_env_file_still_warns_through_settings
- test_raw_ceiling_far_below_the_measured_ratio_is_rejected
- test_deprecated_flush_bytes_env_var_warns_and_is_ignored
- test_oversized_turn_is_split_not_truncated
- test_chunk_smaller_than_flush_is_rejected
- test_deprecated_flush_bytes_in_an_env_FILE_also_warns
- cli.py
- protection.py
- ProtectionOperation
- Database
- test_account_billing_routes.py
- _seed_similar_nodes
- _make_settings_mock
- test_scoring_signals.py
- IngestSpool
- hippocampus.py
- account.py
- billing.py
- forgetting_manager.py
- bundle.py
- test_whisper_log_cleanup_settings_must_be_positive
- test_validate_llm_runtime_config_rejects_ollama_with_anthropic_default
- test_validate_llm_runtime_config_rejects_empty_ollama_model
- test_validate_llm_runtime_config_keeps_claude_cli_default
- test_settings_construction_with_bad_pair_still_succeeds
- test_expired_nodes_excluded
- test_non_expired_node_not_filtered
- test_low_confidence_penalized_more
- test_minmax_normalization_spreads_scores
- test_single_result_normalization
- test_fts_query_rewrite_user_name
- test_fts_query_rewrite_no_identity
- test_fts_query_rewrite_user_likes_grapes
- test_vector_fallback_on_encoder_failure
- test_tag_filtering_uses_batch
- test_rrf_overlap_accumulates
- test_fts_porter_stemmer
- test_very_long_content_heavily_penalized
- test_question_query_favors_vector_over_fts_title
- test_keyword_title_boost_still_active
- test_capitalism_query_ranks_correctly
- state.py
- .test_trailing_pair_is_unsafe_until_next_user
- .test_legacy_mid_response_cursor_drops_orphan
- StoreLock
- parse_transcript
- get_fastembed_cache_dir
- test_cloud_state.py
- _install_hooks
- synthetic_pattern_monitor.py
- entitlements.py
- restore.py
- consolidator.py
- test_cloud_recovery.py
- MaintenanceManager
- _find_binary
- pair_batch.py
- get
- routes_ui.py
- routes_ingest.py
- prompt_classifier.py
- NodeFileHandler
- HTTPException
- console.py
- EmbeddingAdapter
- relevance_quarantine.py
- format_node_with_neighbors
- store_lock.py
- embeddings/__init__.py
- jobs.py
- LocalAdapter
- LiteLLMEmbeddingAdapter
- OllamaEmbeddingAdapter
- pair_skip.py
- settings.py
- get_adapter
- cloud/__init__.py
- .connect
- text/__init__.py
- test_a_full_batch_reaches_the_extractor_as_one_chunk

## God Nodes (most connected - your core abstractions)
1. `MemoryEngine` - 117 edges
2. `_make_node_dict()` - 85 edges
3. `_mark_idle()` - 75 edges
4. `Settings` - 69 edges
5. `CloudProtectionService` - 67 edges
6. `_make_jsonl()` - 66 edges
7. `_settings()` - 60 edges
8. `Database` - 53 edges
9. `CloudClient` - 48 edges
10. `ok()` - 48 edges

## Surprising Connections (you probably didn't know these)
- `test_logout_revokes_before_local_deletion_and_preserves_other_keys()` --indirect_call--> `settings()`  [INFERRED]
  test_cli_account.py → conftest.py
- `test_status_json_contains_no_token()` --indirect_call--> `settings()`  [INFERRED]
  test_cli_account.py → conftest.py
- `test_fallback_runs_backfill_off_thread()` --indirect_call--> `engine()`  [INFERRED]
  test_main_backfill_fallback.py → conftest.py
- `test_offline_verification_preserves_known_good_verification_health()` --calls--> `FakeCloudClient`  [INFERRED]
  test_cloud_protection.py → test_cloud_jobs.py
- `test_verification_rejects_invalid_server_snapshot_id_before_tempfile()` --calls--> `FakeCloudClient`  [INFERRED]
  test_cloud_protection.py → test_cloud_jobs.py

## Import Cycles
- None detected.

## Communities (334 total, 61 thin omitted)

### Community 0 - "test_session_watcher.py"
Cohesion: 0.02
Nodes (206): _append_assistant(), _append_codex_turn(), _append_pair(), _append_user(), _drain_all(), _handler_with_spool(), _make_jsonl(), _mark_idle() (+198 more)

### Community 1 - "patch"
Cohesion: 0.01
Nodes (69): patch, Tests for shared space detection., test_detect_fallback_to_cwd_basename(), test_detect_from_git_repo(), test_detect_from_git_subdirectory(), test_detect_handles_git_not_found(), test_detect_handles_git_timeout(), test_detect_returns_none_for_home() (+61 more)

### Community 2 - "FakeCloudClient"
Cohesion: 0.06
Nodes (58): cloud_state_dir(), FakeCloudClient, _patch_upload_prerequisites(), _patch_verification(), fixture, MemoryNode, parametrize, Path (+50 more)

### Community 3 - "session_watcher.py"
Cohesion: 0.06
Nodes (50): Re-admit new LLM calls after a RECOVERABLE cancel (the watcher's startup…, resume_llm_adapters(), _assistant_response_after_prompt(), _commit_state(), _drain_handlers(), _feedback_llm_judge_enabled(), _file_hash(), _ingest_session() (+42 more)

### Community 4 - "test_conflict_detector.py"
Cohesion: 0.06
Nodes (54): _conflict_response(), _create_pair(), _make_belief(), Tests for LLM-based contradiction detection in conflict_detector., LLM rejects contradiction -> no edge, no proposal., Helper: create two similar nodes without auto-linking, return their IDs., LLM returns None -> pair is skipped, no proposals created., With llm_provider='none', LLM is never called and no proposals created. (+46 more)

### Community 5 - "test_synthetic_pattern_monitor.py"
Cohesion: 0.06
Nodes (54): _decision(), Rot detection for the synthetic-prompt pattern list (#143)., council C1. With the filter off nothing writes silent_synthetic, so every…, council I4. One match months ago is not evidence of a live workflow., Rewritten from the old global vacation guard, which the opportunity guard…, The old global guard was satisfied by ONE prompt after a month away and…, The mirror case: the marker really did stop, and there was plenty of traffic in…, History for a pattern the user already deleted is not actionable. (+46 more)

### Community 6 - "test_duplicate_merger.py"
Cohesion: 0.07
Nodes (51): _create_pair(), _duplicate_response(), _make_fact(), Tests for LLM-based duplicate consolidation in duplicate_merger., With llm_provider='none', LLM is never called., For medium-confidence pairs, proposal contains merged content preview., Issue #90: pairs_evaluated must reflect exactly one LLM decision call., Helper: create two similar nodes and return their IDs. (+43 more)

### Community 7 - "TestClaudeCodePluginProvidesHooks"
Cohesion: 0.07
Nodes (19): Path, Verify that run_uninstall deletes the actual memory directory regardless of…, Helper: run uninstall with a faked settings.memory_dir., Old ormah used Path('memory') — server runs from ~, so data is at ~/memory., Custom absolute path outside XDG dirs is also cleaned up., memory_dir under ~/.local/share/ormah is already covered by XDG cleanup., A stale enabled flag must never license deleting the working wiring., An interrupted update can leave the dir without its hooks manifest. (+11 more)

### Community 8 - "test_cloud_enablement.py"
Cohesion: 0.11
Nodes (43): cloud_state_dir(), FakeClient, fixture, parametrize, Path, _ready_intent(), _settings(), _store_id() (+35 more)

### Community 9 - "test_cli_adapter.py"
Cohesion: 0.08
Nodes (44): _mock_response(), Tests for the CLI adapter., Run the CLI with given args, returning (exit_code, stdout, stderr)., Create a mock httpx.Response., When cwd is missing, space should be None (no space key in body)., Nudge appears at the Nth prompt (default 10)., Nudge never appears when interval is 0., Each session_id gets its own counter. (+36 more)

### Community 10 - "test_cloud_bundle.py"
Cohesion: 0.06
Nodes (38): backup_dir(), _dir_hashes(), _encrypted_tar(), keypair(), fixture, parametrize, Tests for encrypted snapshot bundles: round-trip, tamper detection, and the…, Decrypt a bundle, let `mutate` alter the member dict, re-encrypt. (+30 more)

### Community 11 - "test_whisper_out.py"
Cohesion: 0.08
Nodes (29): _concurrent_appender(), _concurrent_drainer(), _isolate_cache(), _make_transcript(), _mock_client(), _outbox_records(), fixture, skipif (+21 more)

### Community 12 - "routes_admin.py"
Cohesion: 0.09
Nodes (42): _backup_service_from_request(), backup_status(), _backup_status_payload(), _backup_to_dict(), BackupSettingsUpdate, cloud_status(), create_backup(), _guard() (+34 more)

### Community 13 - "IngestSpool"
Cohesion: 0.05
Nodes (55): IngestSpool, app(), client(), fixture, Path, Tests for POST /ingest/nudge (ADR-0004 slice 1, Task 3). The endpoint enqueues…, Two paths for one transcript must not become two independent ingests., The hook drops its outbox record on a 202. If the file is not on disk by then,… (+47 more)

### Community 14 - "keys.py"
Cohesion: 0.07
Nodes (59): Identity, _cmd_cloud_init(), generate_identity(), identity_from_str(), identity_to_str(), _atomic_write_0600(), CloudKeyError, current_recipient() (+51 more)

### Community 15 - "test_ingest_extraction.py"
Cohesion: 0.05
Nodes (40): Extraction error classification: timeout/call-failure must not read as 'no…, If every chunk's call fails while a provider is configured, the whole…, Extracted memories below ingest_min_confidence are dropped before node creation., A single line (turn) longer than hard_cap is split into <=hard_cap pieces,…, An oversized turn between normal turns is split without dropping any turn or…, min(max(baseline, derived), max) still returns `max` when max < baseline --…, num_predict bounds OUTPUT; num_ctx bounds INPUT. Leaving num_ctx unset inherits…, The constructor default must never be what ships -- the value an operator sets… (+32 more)

### Community 16 - "test_memory_engine.py"
Cohesion: 0.05
Nodes (17): Tests for the memory engine., whisper fires onboarding nudge exactly once when identity is empty., Identity protection must be active on the production call path (I3)., Reranker unavailable (fresh install, model downloading) must degrade to…, Desktop setup may cache the reranker after the server already started. The next…, Whisper may load an already-cached reranker, but must not download it., Concurrent recalls must not each construct a HybridSearch (#27). Without…, Calling remember() without a title should auto-generate one from content. (+9 more)

### Community 17 - "CloudClient"
Cohesion: 0.11
Nodes (20): BaseTransport, _client_version(), CloudClient, CloudError, get_or_create_device_id(), Any, Path, RuntimeError (+12 more)

### Community 18 - "test_consolidator.py"
Cohesion: 0.05
Nodes (20): consolidation_engine(), fixture, integration, skipif, Tests for the memory consolidation background job., Consolidated node should inherit the majority space., Engine with several similar working memories., An empty/blank summary is a no-op that must still record the signature. (+12 more)

### Community 19 - "routes_account.py"
Cohesion: 0.11
Nodes (38): account_checkout(), _account_http_error(), account_logout(), account_offer(), account_portal(), account_request_code(), account_status(), account_verify_code() (+30 more)

### Community 20 - "IndexBuilder"
Cohesion: 0.08
Nodes (33): IndexBuilder, Path, Index builder: full rebuild and incremental updates from markdown files., Update index for changed/new files. Returns (added, updated) counts., Index or re-index a single file., The stored fingerprint + seq, read BEFORE _remove_node deletes the row. Only…, Index a single markdown file into the database (nodes + edges)., Builds and updates the SQLite index from markdown source files. (+25 more)

### Community 21 - "test_merge_undo.py"
Cohesion: 0.08
Nodes (35): _create_node(), Tests for execute_merge and undo_merge operations., When remapping creates a self-loop, the edge is dropped., When remapping would duplicate an existing edge, it's skipped., execute_merge creates a record in merge_history., Undoing a merge restores the removed node., When merging nodes of different tiers, the higher-tier node is kept., Undoing a merge restores the removed node's original edges. (+27 more)

### Community 22 - "auto_linker.py"
Cohesion: 0.05
Nodes (69): _find_link_candidates(), _get_watermark(), _llm_classify_link(), _node_dict(), Automatic edge creation based on embedding similarity., Render one candidate pair for a batched link prompt (#87)., Ask LLM to classify the relationship between two nodes. Returns a dict with…, Convert a DB row to a plain node dict for candidate lists. (+61 more)

### Community 23 - "_make_node_dict"
Cohesion: 0.08
Nodes (15): _make_node_dict(), Whisper formatting: flat list, top 2 full, rest title-only., Precision helpers should favor the most relevant whisper candidate., An unbroken (space-free) string must not exceed the cap by one., Whisper outputs a flat ranked list — top 2 full, rest title+ID only., Whisper cross-encoder reranking with linear-rescale blended scoring., Blended scoring should preserve semantically relevant results even when cross-…, Results with both low CE and low embedding scores should be filtered. (+7 more)

### Community 24 - "test_seq_fingerprint.py"
Cohesion: 0.10
Nodes (35): _make_node(), Conditional seq allocation driven by a persisted content fingerprint (#126)., auto_cluster dual-writes `space`: straight into SQLite AND into the markdown., Content feeds the embedding and the judge prompt., Type is shown to the LLM judge., Tags feed FTS, never the linker., A row whose file on disk no longer matches its file_hash has a pending reindex.…, A row whose file matches its hash is stamped, so the upgrade does not requeue… (+27 more)

### Community 25 - "test_cloud_keys.py"
Cohesion: 0.06
Nodes (10): key_path(), fixture, parametrize, Tests for cloud key lifecycle, store_id, and the recovery kit., End-to-end: a bundle encrypted to the current key opens with identities re-…, A kit whose store_id line is damaged must abort, not fall through to minting a…, test_extract_store_id_fails_closed_on_malformed(), test_kit_keys_open_real_bundle() (+2 more)

### Community 26 - "test_eval_whisper/test_metrics.py"
Cohesion: 0.06
Nodes (8): Tests for eval/whisper/metrics.py., TestComputePromptMetrics, TestF1Score, TestFalsePositive, TestInjectionPrecision, TestInjectionRecall, TestSuppressionCorrect, TestTop2Recall

### Community 27 - "CloudProtectionService"
Cohesion: 0.09
Nodes (36): key_file_exists(), _backup_for_upload(), _backup_matches_memory(), _cleared_upload_journal(), CloudProtectionService, _existing_store_id(), _is_disk_full_error(), _is_offline_error() (+28 more)

### Community 28 - "_settings"
Cohesion: 0.06
Nodes (34): Create settings with overrides, using a temp dir for memory_dir., _settings(), test_claude_cli_timeout_default_is_valid(), test_cloud_backup_interval_zero(), test_consolidation_interval_zero(), test_consolidation_inverted_bounds_rejected(), test_consolidation_threshold_non_finite(), test_consolidation_threshold_out_of_range() (+26 more)

### Community 29 - "test_feedback_schema.py"
Cohesion: 0.11
Nodes (33): _index_exists(), _make_db_without_new_tables(), _make_legacy_affinity_db(), Path, Tests for whisper_log, affinity, and review_log schema additions., Feedback is capped per whisper event, not per whole session., Create a DB, init schema, then drop the three new tables to simulate an older…, Calling _migrate() on an already-migrated DB must not raise. (+25 more)

### Community 30 - "test_config.py"
Cohesion: 0.06
Nodes (26): Tests for config validation., test_activation_decay_one_ok(), test_activation_decay_zero(), test_affinity_defaults(), test_backup_defaults(), test_backup_interval_zero(), test_backup_retention_zero(), test_claude_cli_timeout_must_be_positive() (+18 more)

### Community 31 - "test_routes.py"
Cohesion: 0.07
Nodes (17): client(), fixture, Tests for API routes., CH2: with no scheduler, a degraded fallback makes /admin/health degraded., Inverse: a healthy fallback (flag False) leaves health ok., Issue #90 (dev council follow-up): a Phase 1 with a broken finder must still…, CR2: scheduler present + embedding_backfill last run failed -> health degraded., A later success after an error leaves health ok. (+9 more)

### Community 32 - "test_pair_batch.py"
Cohesion: 0.09
Nodes (19): Issue #87: pair batching — settings, timeout hint, batch module., Council R2: zero-usable gets ONE half-size probe, never the full tree., The bound applies to ZERO_USABLE only — unparseable keeps today's tree., Council C1: an outage must not iterate the whole collected list., _settings(), test_explicit_k_overrides_settings(), test_k1_is_a_pure_map_over_judge_single(), test_llm_unavailable_aborts_remaining_chunks() (+11 more)

### Community 33 - "TestSubmitFeedbackBasic"
Cohesion: 0.10
Nodes (6): _insert_review_log(), _insert_whisper_log(), fixture, Tests for engine.submit_feedback and POST /agent/feedback route., TestSubmitFeedbackBasic, TestSubmitFeedbackRoute

### Community 34 - "TestSafeBoundary"
Cohesion: 0.06
Nodes (16): safe_* must exclude a dangling user turn; raw fields still include it., tool_use followed by a text assistant must form ONE pair, not fragment. The…, A trailing tool-only assistant (no text) leaves the pair pending (known…, A multi-record assistant response at EOF must not be committed mid-stream. The…, Once the next user turn arrives, the full multi-record response is one safe…, A terminal stop_reason (Claude Code) closes the response immediately — the safe…, A multi-record response (tool_use then end_turn) is one safe pair, never split…, If the user interrupts a non-terminal response, the next user turn still closes… (+8 more)

### Community 35 - "test_forgetting_manager.py"
Cohesion: 0.18
Nodes (29): _archival_count(), _backdate_tombstone(), _break(), _enable(), _exists(), _make_archival_recent(), _make_eligible(), parametrize (+21 more)

### Community 36 - "test_hippocampus.py"
Cohesion: 0.07
Nodes (29): Tests for the hippocampus file-watching & auto-ingestion layer., Same hash means the file is not re-ingested., Only .md files are picked up by scan., Rapid writes result in a single ingestion call., State file survives across load/save cycles., Git repo path produces correct space name., hippocampus_enabled=False returns no observers., run_hippocampus_scan ingests files from configured dirs. (+21 more)

### Community 37 - "_make_vec"
Cohesion: 0.10
Nodes (19): _insert_affinity_row(), _make_affinity_db(), _make_vec(), Connection, ndarray, Tests for the affinity boost module (adaptive feedback loop)., node_ids that have no rows do not appear in the result., Results are scoped to the requested node_ids only. (+11 more)

### Community 38 - "test_cleanup_auto_ingested.py"
Cohesion: 0.15
Nodes (22): _FakeBackupService, _FakeBuilder, _FakeEngine, _FakeFileStore, _FakeInfo, _make_nodes(), Path, Cleanup script: dry-run is read-only; apply removes only non-preserved sources. (+14 more)

### Community 39 - "test_cloud_client.py"
Cohesion: 0.14
Nodes (25): mock, parametrize, test_auth_and_entitlement_requests_match_service_shapes(), test_create_checkout_session_fails_closed_on_malformed_checkout_required(), test_create_checkout_session_handles_non_checkout_statuses(), test_create_checkout_session_propagates_rate_limit(), test_create_checkout_session_rejects_non_uuid_intent(), test_create_checkout_session_rejects_past_or_absurd_expiry() (+17 more)

### Community 40 - "test_mutation_stamping.py"
Cohesion: 0.17
Nodes (27): _backdate(), _create(), Mutation-stamping guarantees (Sync v1 Step 0). Every content mutation must…, Create a node with auto-linking suppressed, return its id., Phase-2 repaired defines edges must live in the self node's markdown so they…, Parse the tombstone file for a node from deleted/., _reset_adapter(), test_auto_cluster_advances_updated() (+19 more)

### Community 41 - "test_spreading_activation.py"
Cohesion: 0.16
Nodes (28): _connect(), _filter_user_node(), _make_result(), Tests for spreading activation in recall., contradicts propagates less activation than supports, and is labelled as…, Empty results in, empty results out., format_search_results separates direct hits from activated., format_search_results shows contradicts-activated results under 'Conflicting… (+20 more)

### Community 42 - "test_importance_scorer.py"
Cohesion: 0.07
Nodes (26): fixture, Tests for the importance scoring background job., Absolute normalization: adding a high-access outlier shouldn't shift existing…, Engine with a few nodes of varying profiles., Recently accessed node should score higher than an old one., Edge count should be fetched with batch queries, not N per-node queries., Custom weights that don't sum to 1.0 should still produce valid [0, 1] scores., Confidence factor in search should rank high-confidence above low-confidence. (+18 more)

### Community 43 - "TestOutputFunctions"
Cohesion: 0.07
Nodes (10): fixture, Tests for ormah console output formatting., In non-TTY mode, Spinner prints [..] lines instead of animating., Updating with the same message shouldn't print again., Spinner cleans up even on exception., Reset color detection cache before each test., _reset_color(), TestColorDetection (+2 more)

### Community 44 - "test_server_manager.py"
Cohesion: 0.07
Nodes (19): Tests for server lifecycle helpers: port-conflict detection and launchd plist., A ThrottleInterval backstops genuine crash loops., A healthy Ormah listener makes a duplicate foreground start a no-op., A foreign listener must make the supervisor retry instead of going dormant., A bound, listening socket is reported as in use., When the port is free, uvicorn is launched as normal., A port with no listener is reported as free., An IPv6 host literal must not fail the pre-flight probe. (+11 more)

### Community 45 - "test_hybrid_search.py"
Cohesion: 0.08
Nodes (22): parametrize, Tests for hybrid search scoring mechanics. These test the RRF fusion, threshold…, All identity tokens should be in the stop words list., A query with only identity tokens (all stopped) should fall back to raw tokens…, my email' should inject about_self alongside 'email'., Should never return more results than the limit., Higher weight should give proportionally higher contribution., Verify that FTS query uses bm25 column weights (title 10x, tags 5x). This is an… (+14 more)

### Community 46 - "ControlledEncoder"
Cohesion: 0.16
Nodes (12): ControlledEncoder, Test classification decisions with controlled cosine similarities., When prompt vector is identical to an archetype, it should match., When prompt doesn't match any archetype, return general., Conversational only applies when it's the sole match., If conversational + temporal both match, conversational is removed., Conversational should win when other matches are far below its score., Multiple non-conversational intents can co-exist. (+4 more)

### Community 47 - "test_protection_routes.py"
Cohesion: 0.09
Nodes (10): FakeRecoveryKitService, _poll(), protection_app(), fixture, parametrize, Path, test_long_operations_return_202_and_poll_safe_results(), test_malformed_recovery_digest_is_rejected_before_service_work() (+2 more)

### Community 48 - "_insert_injected_whisper_log"
Cohesion: 0.14
Nodes (20): _insert_injected_whisper_log(), Once a judge signal exists, the same whisper row is not judged again., Clear references in an assistant response create a signal and affinity row., Unreferenced whispers are observable but do not become negative affinity., The transcript watcher does not call the LLM unless the judge is enabled., A confident LLM 'used' verdict creates positive affinity for an ambiguous row., When the schema call fails, the judge gives up rather than retrying without a…, A confident LLM irrelevant verdict is the automatic negative-feedback path. (+12 more)

### Community 49 - "test_main_lifespan_shutdown.py"
Cohesion: 0.10
Nodes (20): _fake_lifespan_deps(), asyncio, fixture, Bounded scheduler shutdown + engine.shutdown() policy (Fix A / Fix D). Tests…, R1: each lifespan execution must create a NEW threading.Event in…, Patch main.lifespan's heavy dependencies. Mirrors the fakes at L249-288., R7 HIGH-2 regression. When start_session_watcher() raises, main.lifespan…, The adapter caches and the cancellation epoch are module-level and outlive a… (+12 more)

### Community 50 - "test_backup.py"
Cohesion: 0.21
Nodes (21): BackupService, _active_self(), MemoryNode, Path, _save_node(), _save_self_node(), _service(), _set_active_self() (+13 more)

### Community 51 - "test_claude_cli_adapter.py"
Cohesion: 0.13
Nodes (19): _fake_popen(), ITEM 1 (council-pr R4, Codex) DATA INTEGRITY: the final gate read the LIVE…, council R2 (critical): Popen raising FileNotFoundError/OSError returns None…, council R6: a recoverable cancellation (startup rollback) must not poison the…, Factory for a monkeypatch-ready fake subprocess.Popen. The returned callable…, test_adapter_generates_again_after_a_rollback_cancellation(), test_argv_denies_all_tools(), test_argv_pins_model_and_json_output() (+11 more)

### Community 52 - "test_job_tracker.py"
Cohesion: 0.08
Nodes (7): Tests for background job tracker., A run_* that returns {"error": ...} must be recorded as a FAILURE, not a…, A runner that dies signals it by RETURNING {'error': ...} (it catches its own…, run_restore_verification returns a bool — False means the restore could NOT be…, test_tracked_error_dict_return_records_failure(), test_tracked_records_a_failure_when_the_job_returns_an_error_dict(), test_tracked_records_a_failure_when_the_job_returns_false()

### Community 53 - "_make_titled_hybrid"
Cohesion: 0.08
Nodes (24): _make_titled_hybrid(), Two results at adjacent ranks in both lists (spread ~1.6%) should use max-norm…, Question query with FTS and vec disagreement — semantic match should still win…, Create a HybridSearch with titled nodes and optional content lengths., A node with the query term in its title scores higher than one with it only in…, Title match should work even when title contains punctuation (e.g., commas)., A long document with moderate vector similarity scores lower than a short one…, With length_penalty_threshold=0, no penalty is applied — long and short score… (+16 more)

### Community 54 - "test_whisper_context.py"
Cohesion: 0.11
Nodes (14): _make_engine_with_encoder(), Tests for whisper context (involuntary recall injection)., Create a mock engine with a hybrid search encoder that returns a fixed vector., The injection gate cuts absolute signals (ce_absolute / raw_cosine), never the…, Without the reranker, the gate falls back to raw_cosine, not the blended score., Results carrying neither absolute signal keep pre-contract gate behavior…, The gate re-applies cross-space demotion the absolute signal drops: a wrong-…, The gate re-applies the confidence factor: a low-confidence memory the cosine… (+6 more)

### Community 55 - "_write_jsonl"
Cohesion: 0.15
Nodes (4): Path, Write a list of dicts as JSONL to a temp file and return the path., TestParseTranscript, _write_jsonl()

### Community 56 - "MemoryEngine"
Cohesion: 0.07
Nodes (24): MemoryEngine, client(), fixture, Proves engine-calling routes run in the threadpool, not serialized on the loop., fixture, ui_app(), A variable payload against a fixed provider timeout is the bug. The hint must…, Council R1, both peers: adapters treat the hint as a REPLACEMENT… (+16 more)

### Community 57 - "test_stats.py"
Cohesion: 0.12
Nodes (19): _log_decision(), _log_whisper(), fixture, Tests for the canonical /stats endpoint., Candidates that were logged but not injected don't count as used., GET /agent/clients returns the agent list with detection and wired status., silence_rate + injection_rate must cover all prompts., Insert a synthetic whisper_log row mirroring context_builder's writer. (+11 more)

### Community 58 - "_NeverEofProc"
Cohesion: 0.10
Nodes (14): _NeverEofProc, A child whose pipes NEVER reach EOF — models the setsid grandchild that…, R3 + R5 regression. A child that HANDLES SIGTERM and exits 0 emits partial…, MEDIUM-E (council, Codex): a provider timeout still returns None in this slice…, B-1: base subprocess.run's timeout path does process.kill(); process.wait() --…, HIGH-2 (council-pr R3, Codex): a setsid grandchild escapes the group kill AND…, council-pr R5 MEDIUM (Cursor 0.85) — same root cause via the semaphore. `gen`…, codex R3 race: generate() is paused between process creation (Popen returning)… (+6 more)

### Community 59 - "test_adapters.py"
Cohesion: 0.09
Nodes (8): Tests for embedding adapters and the provider registry., A populated store refuses a dim change; allow_drop authorizes it., TestDimensionMismatch, TestGetAdapter, TestGetEncoderCaching, TestLiteLLMAdapter, TestLocalAdapter, TestOllamaAdapter

### Community 60 - "test_self_node.py"
Cohesion: 0.09
Nodes (21): Tests for the user self node feature., Preference with about_self=True stays working tier (consolidator handles dedup)., Person type with about_self=True should be promoted to core tier., Fact with about_self=True stays working tier (only preference/person promoted)., Decay manager should skip the self node., Self node ID should be stored in the meta table., Self node should be reused across engine restarts., Self node should never be demoted when core cap is enforced. (+13 more)

### Community 61 - "._builder"
Cohesion: 0.13
Nodes (9): Standing rules use a typed applicability channel without biasing facts., A weak query's least-bad match: blended ~0.9 (rank-relative top) but the cross-…, A genuinely relevant match under-ranked by the bi-encoder: the cross-encoder…, Topic-shift suppression only fires for topics that were served (I9)., Turn 1 was gate-rejected (logged was_injected=0); turn 2 on the same topic must…, Turn 1 injected (was_injected=1); turn 2 on the same topic is correctly…, Without a session_id there is no served history — the plain topic-shift skip…, TestPreferenceApplicability (+1 more)

### Community 62 - "TestSyntheticPromptEndpoint"
Cohesion: 0.13
Nodes (8): A machine-generated turn is skipped at the /agent/whisper boundary, BEFORE any…, matches everything and is falsy — the guard must test `is not None`. Truthiness…, Kill-switch coverage: it was dropped in 566fe3a when the guard moved., Rot detection is impossible without knowing WHICH pattern matched (#143)., Only silent_synthetic rows carry a pattern; everything else stays NULL., Dead sessions are evicted from _session_buffers on access (I12)., TestSessionBufferEviction, TestSyntheticPromptEndpoint

### Community 64 - "TestValidateCase"
Cohesion: 0.10
Nodes (4): Tests for eval/whisper/corpus.py., TestLoadCorpus, TestValidateCase, _write_jsonl()

### Community 65 - "TestTimeExtraction"
Cohesion: 0.15
Nodes (6): Tests for extract_time_params (bounded time windows)., last 2 weeks' uses rolling previous-period: 4w ago → 2w ago., last 1 week' (N=1) extends to now, not rolling., last 3 months' uses rolling: 6m ago → 3m ago., PromptClassifier._extract_time_params still works., TestTimeExtraction

### Community 66 - "test_main_backfill_fallback.py"
Cohesion: 0.13
Nodes (20): fixture, Scheduler-independent embedding backfill fallback (#32, council C2/CH1/CH2).…, CH1: a second start while one is alive does not spawn a second thread., CH1: _stop_backfill_fallback stops a permanently-failing fallback., C1: se o join expira (encode travado), _stop retorna True e handle é mantido…, C1: quando o thread sai antes do timeout, _stop retorna False e handle é limpo., M-A: _stop_backfill_fallback must NOT return while the thread is alive.…, C2: fallback does not give up after 5 attempts — retries until success. (+12 more)

### Community 67 - "FakeCloudClient"
Cohesion: 0.18
Nodes (14): account_paths(), build_client(), FakeCloudClient, fixture, parametrize, Tests for token-free local account authentication adapters., test_account_email_rejects_unicode_line_separators(), test_logout_revokes_first_then_clears_locally_even_offline() (+6 more)

### Community 68 - "test_run_stats.py"
Cohesion: 0.11
Nodes (16): Issue #90: maintenance runs return a stats dict., run_consolidation calls _find_consolidation_clusters directly and has no catch-…, At the 1440-minute defaults the nominal offsets (5/15/30/45) are unscaled —…, Issue #90 council R3 finding 2: scaling each job by ITS OWN interval let jobs…, A run whose internals raise must NOT look like a clean, empty success., Issue #90 council R2 finding 1: a DB/encoder failure inside the finder must not…, Same as above for duplicate_merger's finder (also only reachable via…, Issue #90 council R2 finding 1: unlike auto_linker/duplicate_merger,… (+8 more)

### Community 69 - "test_cli_cloud_backup.py"
Cohesion: 0.14
Nodes (13): _cloud_status(), _local_status_service(), MemoryNode, parametrize, Path, RestoreClient, _save_node(), test_backup_status_json_contains_cloud_section() (+5 more)

### Community 70 - "test_relevance_runner.py"
Cohesion: 0.19
Nodes (16): _FakeEngine, Path, Tests for eval/relevance/runner.py (the in-context relevance-gate ship gate).…, Stands in for MemoryEngine; only needs _extract_memories_llm., test_labels_for_returns_empty_on_extractor_error_string(), test_labels_for_returns_multiple_labels(), test_labels_for_returns_provenance_list(), test_main_all_mixed_corpus_fails() (+8 more)

### Community 71 - "test_parser.py"
Cohesion: 0.13
Nodes (19): Tests for agent JSONL transcript normalization., A transcript whose RAW bytes dwarf its CLEANED conversation. Each turn carries…, The running counter and the rendered payload must not be able to drift. Both go…, The regression Amendment 3 exists to kill: tool-heavy turns must BATCH. Each…, A multi-turn slice's committed conversation stays within the budget — break…, The commit-site asymmetry: at the terminal-assistant site the budget check runs…, The progress guard: a lone turn bigger than the budget can't be shrunk, so it…, Tiny conversation, enormous raw span: the content budget is nowhere near full,… (+11 more)

### Community 72 - "conftest.py"
Cohesion: 0.16
Nodes (18): _clean_llm_cancel_epoch(), db(), engine(), file_store(), _is_real_ormah_path(), _is_relative_to(), isolate_fastembed_cache(), _isolate_settings_from_global_env() (+10 more)

### Community 73 - "test_auto_linker.py"
Cohesion: 0.11
Nodes (17): Tests for LLM-based edge type classification in auto_linker., A mass reindex must not leave a stale watermark hiding the whole store., Council C1 regression: LLM down -> exactly one batch attempt, watermark held., Cursor regression: no pair is judged once the edge budget is spent (K=1 path)., A concurrent writer created the same edge between collection and apply.…, The winner committed the DB row but crashed before saving its markdown. The…, A run that dies must say so in its return value — the job tracker and the admin…, The LLM can return JSON-valid garbage like {"reason": 123}. SQLite accepts the… (+9 more)

### Community 74 - "test_ingest.py"
Cohesion: 0.08
Nodes (28): _canned(), integration, parametrize, skipif, Tests for conversation ingestion: dry_run, confidence, truncation., Real claude_cli round-trip: mandatory schema must survive an actual `claude -p`…, dry_run=True should return extracted memories without calling remember()., Verify no nodes are created during dry_run. (+20 more)

### Community 75 - "test_temporal_search.py"
Cohesion: 0.14
Nodes (13): _make_node(), mock_hybrid(), fixture, Tests for temporal query filters (created_after / created_before)., Temporal + type filters should combine with AND semantics., HybridSearch with mocked internals — no real DB or encoder., Run search with all three nodes returned by both retrievers., _run_search() (+5 more)

### Community 76 - "_insert_node"
Cohesion: 0.12
Nodes (11): _insert_node(), When topical results survive, identity should still be included., identity-only intent with no search results should stay silent (no graph dump)., Whisper should respect max_nodes., Total nodes in output should be <= max_nodes, even with identity nodes., Identity-only intent should still run search (not skip it)., Identity results should be suppressed when no topical results survive., Low-scoring identity results should be suppressed when no topical results… (+3 more)

### Community 77 - "_make_node"
Cohesion: 0.16
Nodes (9): _make_node(), MemoryNode, Tests for enriched node fields in markdown serialization., Nodes without the new fields should get sensible defaults., Roundtrip serialization with all enrichment fields., Confidence must be between 0.0 and 1.0., TestConfidenceValidation, TestLegacyParsing (+1 more)

### Community 78 - "TestReleaseVersionVerification"
Cohesion: 0.19
Nodes (7): CompletedProcess, Path, Tests for release packaging metadata and CLI fallbacks., TestBuildMetadata, TestEvalCliFallback, TestReleaseVersionVerification, TestReleaseWorkflow

### Community 79 - "_create_pair"
Cohesion: 0.11
Nodes (18): _create_pair(), Helper: create two similar nodes without auto-linking, return their IDs., Pairs classified as 'none' should be recorded in auto_link_checked., Re-writing a node's content bumps its seq to the head (crit#2 mechanism)., A direct metadata UPDATE (not via the builder) must not change seq., The winner of the race already wrote its Connection to the file. We must not…, An INSERT OR IGNORE that inserted nothing is not a creation. Counting it as one…, The markdown is the source of truth: a rebuild recreates the edge table from… (+10 more)

### Community 80 - "_reset_adapter"
Cohesion: 0.11
Nodes (18): Pairs already checked should not trigger a second LLM call on re-run., crit#1: a transient None must not let the watermark pass the node., imp#4: max_edges mid-run must not advance the watermark past unprocessed nodes., #126: pairs_judged must cap LLM calls even when every verdict is 'none'…, Updating a node's content should clear its checked pairs so it gets re-…, Issue #90: pairs_evaluated must reflect exactly one LLM decision call. Uses the…, Issue #90 (council finding 2): an LLM-unavailable pair (None decision) must…, Issue #90 council R2 finding 2: the 'error' sentinel (invalid/malformed LLM… (+10 more)

### Community 81 - "test_cloud_cli.py"
Cohesion: 0.19
Nodes (17): CLI tests for the `ormah cloud` group., `ormah cloud kit` is the recovery path when init/rotate is interrupted between…, Fresh-machine import must adopt the kit's store id, not mint a new one — the…, A damaged store_id line must abort the whole import before any key material is…, _run(), test_cloud_init_import_key(), test_cloud_init_json(), test_cloud_init_refuses_second_run() (+9 more)

### Community 82 - "_run_fusion"
Cohesion: 0.11
Nodes (18): Run search with controlled FTS and vector outputs., A result with strong semantic match should outrank one with only keyword match., A result strong in both FTS and vector should outrank single-source results., Vector results below similarity_threshold should not contribute to scoring., Search should use get_nodes_batch instead of individual get_node calls., High-similarity vector result should score significantly higher than low-…, A result in FTS but not in vector results should score lower than one in both., Results below min_result_score should be excluded. With normalized RRF +… (+10 more)

### Community 83 - "TestWhisperTopicShift"
Cohesion: 0.11
Nodes (10): Topic-shift detection: skip injection when prompt is on the same topic., High similarity to recent prompts → skip whisper., Low similarity to recent prompts → proceed with whisper., Underspecified follow-up prompts should still search even on same topic., Empty recent_prompts (cold start) → always inject., None recent_prompts (cold start) → always inject., topic_shift_enabled=False → never skip, even if same topic., If encoder raises, should fall through to normal whisper. (+2 more)

### Community 84 - "test_init_vec_table_guard.py"
Cohesion: 0.15
Nodes (16): _count(), Guard: a dim mismatch must never silently DROP a populated vector store., An empty table is recreated freely and must not burn the one-shot token., TOCTOU: two concurrent init_vec_table(allow_drop=True) calls against the same…, The consumed-marker must accumulate. A later migration must not erase the…, A node_vectors table whose DDL has no FLOAT[dim] (corrupt/foreign schema) must…, MemoryEngine.__init__ authorizes the drop only when the flag equals the…, A consumed reindex authorization must not silently re-authorize a second… (+8 more)

### Community 85 - "test_whisper_health.py"
Cohesion: 0.29
Nodes (14): _db(), _feedback(), _inject(), Connection, test_distinct_guards_against_double_count(), test_empty_store_ratios_none(), test_held_back_candidate_feedback_excluded(), test_injection_without_feedback() (+6 more)

### Community 86 - "integration"
Cohesion: 0.17
Nodes (16): _pid_alive(), integration, Belt-and-suspenders against the real binary: an operator SessionStart hook must…, Belt-and-suspenders against the real binary: a prompt asking to read a probe…, Poll predicate() until True or timeout; returns the final predicate() value., HIGH-2 (council-pr, Codex): `claude -p` forks grandchildren (user-scoped MCP…, HIGH-1 refine (council-pr R2, Codex): the exact edge the poll()-gated per-PID…, HIGH-2 (council-pr R3, Codex): the DETACHED-grandchild bound. The grandchild… (+8 more)

### Community 87 - "test_decay_manager.py"
Cohesion: 0.18
Nodes (16): _get_tier(), _make_stale(), Tests for the decay manager background job., Demoted nodes should have an audit log entry recording the tier change., Set a node's last_accessed to `days` ago., Legacy pending decay proposals should be cleaned up on run., A stale node with high importance should not be demoted., A stale node with low importance should be demoted to archival. (+8 more)

### Community 88 - "test_session_watcher_flush.py"
Cohesion: 0.12
Nodes (10): Presence detection must not fire on a commented-out line or on a longer key…, Regression for review F1: with no ~/.config/ormah/.env and no ./.env,…, The gate fires on the parser's own capped signal, not a pending-chars…, ADR-0001 Amendment 2: a Batch sized to the recall sweet spot must reach the…, Isolates the `ingest_chunk_chars <= ingest_max_content_chars` leg specifically:…, test_chunk_chars_defaults_at_or_above_the_flush_budget(), test_chunk_larger_than_max_content_is_rejected(), test_deprecated_key_scanner_ignores_comments_and_partial_names() (+2 more)

### Community 89 - "test_backfill_embeddings.py"
Cohesion: 0.19
Nodes (16): Tests for MemoryEngine.backfill_embeddings (delta + schema-bump, no quarantine,…, A stop_event that is already set causes backfill to embed nothing., A stop_event that is never set does not interfere with normal completion., An interrupted schema pass must NOT advance embedding_schema_version., Fix B: an interrupted schema pass must NOT delete stale vectors. The DELETE is…, A node that always fails to encode stays genuinely missing (its stale vector is…, _set_schema_version(), _stored_version() (+8 more)

### Community 90 - "test_whisper_claims_investigation.py"
Cohesion: 0.13
Nodes (16): _live_ollama_encoder(), _make_node(), integration, Empirical verification of the claims in docs/investigation-2026-07-15-whisper-…, §3: a topical result displaced by an applicable preference (room_for_main cut…, §1 (revised by the 2026-07-15 live-model experiment): with bge-m3, the EN…, Sanity: the EN patterns the doc compares against do work., §1: 'ontem', 'semana passada', 'últimos N dias' never match _TIME_KEYWORDS. (+8 more)

### Community 91 - "Settings"
Cohesion: 0.06
Nodes (8): BaseSettings, model_validator, _deprecated_key_present(), field_validator, Path, True when an LLM provider is configured (not ``"none"``)., True when the deprecated key is set in ANY configured settings source.…, Settings

### Community 92 - "test_auto_cluster.py"
Cohesion: 0.17
Nodes (15): _connect(), auto_cluster must not propagate the placeholder 'null' space (#22 council…, Startup migration re-locks legacy identity memories once (#22 council C)., The repair resets a swept identity cluster back to global + locked., Happy path still works: an unassigned node inherits a real neighbor space., A user-curated global (space_locked) keeps its None space despite project…, The self/identity node is never swept into a project space., Markdown is source of truth: a node locked in the file but stale-unlocked in… (+7 more)

### Community 93 - "_edges_between"
Cohesion: 0.12
Nodes (16): _edges_between(), LLM returns None -> no edge created (no heuristic fallback)., With llm_provider='none', LLM is never called and no edges are created., Regression (#30): when node_vectors is empty/underfilled (e.g. mid…, Return all edges between two nodes., LLM classifies as supports -> edge created with type supports., A vectorless node must not kill the run: later nodes still get edges, the…, LLM classifies as contradicts -> edge created with type contradicts. (+8 more)

### Community 94 - "test_llm_cancel.py"
Cohesion: 0.12
Nodes (13): _clean_epoch(), fixture, Epoch semantics for LLM cancellation (ADR-0004 slice 2 redesign). These tests…, The watcher logs this count; it replaces the old "processes terminated" number., R4 regression. A resume() re-admits NEW calls; it must never un-cancel a call…, A final cancel must not outlive its lifespan: the llm_client adapter caches are…, R7 HIGH-1 regression — the linearizability assertion. Whichever order the two…, R5 regression. `aborted` answers "is the world cancelled NOW, or was THIS… (+5 more)

### Community 95 - "FakeClient"
Cohesion: 0.21
Nodes (8): FakeClient, parametrize, _run(), test_login_keeps_credentials_when_entitlement_refresh_is_offline(), test_login_persists_credentials_without_rewriting_unrelated_lines(), test_logout_requires_confirmation_in_noninteractive_shell(), test_logout_revokes_before_local_deletion_and_preserves_other_keys(), test_status_json_contains_no_token()

### Community 96 - "_make_node"
Cohesion: 0.17
Nodes (10): _make_node(), Unit tests for HybridSearch title boost score capping. Verifies that…, Multiple query tokens matching title → high title_bonus, but still capped., Even with tier boost + recency + access, final_score capped at 1.0., Build a minimal node dict matching GraphIndex.get_nodes_batch output., Question queries disable title boost, so no cap needed (but shouldn't break)., When title doesn't match, no boost applied, score stays in range., Verify that base_score and final_score are capped at 1.0. (+2 more)

### Community 97 - "_candidate"
Cohesion: 0.04
Nodes (41): _candidate(), _linear_rescale(), Unit tests for the cross-encoder reranker with linear-rescale blended scoring.…, blend_alpha=1 means only CE matters., Verify min_score threshold applies to blended score., Build a minimal search result dict., Verify results are sorted by blended score descending., High CE on a lower-embedding result should promote it. (+33 more)

### Community 98 - "TestWhisperIntentAware"
Cohesion: 0.14
Nodes (8): Whisper should use intent classification to gate/filter results., Conversational prompts should produce no whisper output., General intent should use normal search behavior., Temporal intent should add created_after and created_before to search params., Temporal intent should use stripped search_query instead of raw prompt., If classifier raises, should fall back to normal search., If classifier can't be created (no engine hybrid search), search normally., TestWhisperIntentAware

### Community 99 - "test_entitlements.py"
Cohesion: 0.23
Nodes (11): cache_path(), FakeClient, fixture, parametrize, _settings(), test_cached_entitlement_states(), test_corrupt_cache_is_ignored(), test_missing_cache_refreshes_to_active() (+3 more)

### Community 100 - "test_migrations.py"
Cohesion: 0.33
Nodes (15): _count_conflict_checked(), _count_duplicate_checked(), _create_node(), conflict_checked appears on a standard engine fixture (schema.sql runs on every…, _seed_conflict_checked(), _seed_duplicate_checked(), test_conflict_checked_table_exists(), test_delete_node_invalidates_conflict_checked() (+7 more)

### Community 101 - "test_llm_json.py"
Cohesion: 0.12
Nodes (5): Tests for fence-tolerant LLM JSON parsing shared across background jobs.…, A fenced-but-valid classification must yield the real relationship, not an…, Genuinely unparseable output (no JSON anywhere) yields an "error" result, never…, test_auto_linker_recovers_fenced_response_instead_of_poisoning(), test_auto_linker_treats_unparseable_output_as_poison()

### Community 102 - "TestClient"
Cohesion: 0.32
Nodes (14): _insert_edge(), _insert_node(), Tests for /ui/graph active-first gating and space drill-down., test_default_all_spaces_includes_archival_only_space(), test_default_excludes_archival(), test_default_includes_user_node_even_if_archival(), test_default_no_space_false_when_all_nodes_have_space(), test_default_signals_no_space_group_even_if_archival_only() (+6 more)

### Community 103 - "test_llm_client.py"
Cohesion: 0.15
Nodes (13): _concurrent_first_use(), Tests for the shared LLM facade — provider-configured detection., IMPORTANT-1 (final review). Deleting the post-call `if…, IMPORTANT-2 (final review). Wrapping `ingest_llm_generate`'s call in `except…, Drive two threads into ``factory`` on FIRST use simultaneously and return…, HIGH-1 (council-pr, Codex): two drain threads on distinct acceptance roots…, Same guarantee for the ingest factory (_cached_ingest_adapter): the lock must…, R6 regression. A factory holds _adapter_lock across get_adapter(), and during… (+5 more)

### Community 104 - "test_reuse_stored_vectors.py"
Cohesion: 0.22
Nodes (11): _CountingEncoder, _ExplodingEncoder, Issue #88: pairwise jobs must reuse stored vectors, not re-encode probes., A miss must probe with _embedding_text semantics, not the raw full content.…, test_fallback_encodes_same_truncated_text_as_the_corpus(), test_find_conflict_candidates_does_not_reencode(), test_find_link_candidates_does_not_reencode(), test_find_merge_candidates_does_not_reencode() (+3 more)

### Community 105 - "TestMatchSyntheticPattern"
Cohesion: 0.13
Nodes (3): Which pattern fired — the signal rot detection needs (#143)., The empty regex matches everything and returns "" — falsy but REAL. Callers…, TestMatchSyntheticPattern

### Community 106 - "test_miner.py"
Cohesion: 0.36
Nodes (14): _decision(), _log(), _make_db(), _node(), Path, Regression tests for the whisper eval miner. Build a temp SQLite DB with the…, A live DB predating the whisper_decisions table must fail cleanly, not crash…, _run_mine() (+6 more)

### Community 107 - "test_graph.py"
Cohesion: 0.18
Nodes (12): graph(), _insert_node(), _insert_tag(), fixture, Tests for GraphIndex batch methods., GraphIndex backed by a real test database., Insert a minimal node row directly., Insert a tag for a node. (+4 more)

### Community 108 - "Database"
Cohesion: 0.12
Nodes (11): Database, mock_graph(), fixture, Fixture returning (db, graph) with real schema for whisper_log tests., Ephemeral threads must not leak their per-thread SQLite connection (FD-leak…, test_ephemeral_thread_connection_is_retired(), test_migrate_normalizes_duplicate_payloads_and_preserves_candidate_ids(), The matched_pattern column must appear on pre-#143 databases too. (+3 more)

### Community 109 - "test_llm_adapters.py"
Cohesion: 0.10
Nodes (13): Exception, _FakeSettings, Tests for LLM adapter package., test_get_adapter_litellm(), test_get_adapter_none(), test_get_adapter_ollama(), test_litellm_adapter_failure(), test_llm_generate_none_provider() (+5 more)

### Community 110 - "test_audit_log.py"
Cohesion: 0.20
Nodes (13): _create_node(), Tests for audit logging on delete, update, and mark_outdated., Helper to create a node, returns (id, slug)., delete_node should move the markdown file to deleted/ instead of removing it., Deleting a node writes a full snapshot to the audit log., Updating a node logs the old state and changed fields., Marking a node outdated logs the reason and old valid_until., list_audit_log filters by node_id and operation. (+5 more)

### Community 111 - "TestWhisperContextBuffer"
Cohesion: 0.14
Nodes (8): Context-enhanced search using recent prompts., Underspecified follow-up prompts should use recent context in search., The reranker must score the same context-enhanced query that search ran on, not…, Fully specified prompts should not be polluted by recent context., Without recent_prompts, search query should be the raw prompt., Empty recent_prompts list should use the raw prompt., Only the last 2 recent prompts should be used for follow-up prompts., TestWhisperContextBuffer

### Community 112 - "TestWhisperRerankerBlendIntegration"
Cohesion: 0.12
Nodes (9): Integration tests: blended reranker through the full whisper pipeline. These…, When ALL cross-encoder scores are strongly negative (< -5), results are…, When at least one CE score is > -5, results are NOT suppressed., Custom blend_alpha should affect which results survive., Verify max_doc_chars is forwarded to reranker., Reranker should only affect non-identity search results. Identity nodes are…, Embedding min_score pre-filters; the 0.40 post-boost floor further filters.…, The reranker should change the order of results in the output. (+1 more)

### Community 113 - "TestEvalWhisperCLI"
Cohesion: 0.14
Nodes (3): Tests for eval whisper CLI wiring., TestEvalWhisperCLI, TestMakeEngine

### Community 114 - "test_builder.py"
Cohesion: 0.14
Nodes (11): Tests for index builder., allow_partial=True is the explicit opt-out: a partial pass is committed instead…, A per-file edge-indexing failure must NOT abort the rebuild (edges are derived…, Reindexing a node must not wipe why its edges exist., A rebuild where every file fails to index must NOT persist a truncated index —…, One file succeeding out of many must still abort the rebuild (not just…, test_full_rebuild_aborts_and_preserves_data_on_partial_failure(), test_full_rebuild_aborts_and_preserves_data_on_total_failure() (+3 more)

### Community 115 - "test_setup_json.py"
Cohesion: 0.18
Nodes (11): _isolate_claude_home(), fixture, Tests for the non-interactive JSON setup path used by the Mac app., Structurally block every test in this file from touching the real ~/.claude —…, set_detected(), test_detect_clients_claude_code(), test_detect_clients_codex_via_dir(), test_detect_clients_none() (+3 more)

### Community 116 - "test_markdown.py"
Cohesion: 0.14
Nodes (7): Tests for markdown parsing and serialization., Files written before this change have no `reason` key — they must still load., The parser feeds `reason` straight into a typed pydantic field. A hand-edited…, The reason an edge exists must survive a save/load cycle — the index is rebuilt…, test_a_non_string_reason_in_the_yaml_does_not_make_the_whole_node_unparsable(), test_connection_reason_round_trips(), test_connection_without_reason_still_parses()

### Community 117 - "test_space_normalization.py"
Cohesion: 0.16
Nodes (10): parametrize, Space normalization: placeholder strings persist as None, not literal 'null'…, Only the exact placeholder tokens collapse — names containing them survive., A file corrupted with the literal string 'null' parses back to None., End-to-end migration on a throwaway store: files and index both cleaned., test_markdown_roundtrip_drops_placeholder_space(), test_migration_cleans_placeholder_space_in_files_and_index(), test_near_miss_names_are_preserved() (+2 more)

### Community 118 - "FakeProtectionService"
Cohesion: 0.23
Nodes (5): ProtectionOperationKind, test_checkout_rechecks_cancellation_after_entitlement_fetch(), FakeProtectionService, _operation(), ProtectionOperation

### Community 119 - "test_routes_admin_run_task.py"
Cohesion: 0.15
Nodes (11): app_and_client(), fixture, The manual task-trigger routes must not start a job that is already running,…, A manual trigger during the scheduled run used to start a second concurrent run…, The route returned {'status': 'completed'} unconditionally — a run that blew up…, run-all calls the runners directly too — same hole., The guard is only atomic against a SHARED tracker. It was created inside the…, test_lifespan_always_creates_a_job_tracker_even_if_the_scheduler_fails() (+3 more)

### Community 120 - "test_conflict_claims_investigation.py"
Cohesion: 0.28
Nodes (10): _backdate(), _make_eligible_archival_node(), _mk(), Empirical verification of 6 claims from the conflict-detector / forgetting…, Create a node and backdate it into forgetting eligibility (sans protection)., test_confidence_demotes_in_hybrid_search_and_whisper_gate_and_survives_rebuild(), test_expired_node_leaks_into_spread_activation_via_get_nodes_batch(), test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports() (+2 more)

### Community 121 - "TestMarkOutdated"
Cohesion: 0.15
Nodes (6): feedback_engine(), fixture, Tests for the mark_outdated feedback tool., Engine with a node to give feedback on., An outdated memory should get a lower score in search., TestMarkOutdated

### Community 122 - "FakeEncoder"
Cohesion: 0.22
Nodes (5): FakeEncoder, ndarray, Deterministic encoder that maps specific phrases to known vectors. Uses a…, An encoder that returns zero vectors should not crash., TestLazyInit

### Community 123 - "TestSeedCase"
Cohesion: 0.15
Nodes (4): fixture, Tests for eval/whisper/seeder.py., TestSeedCase, tmp_engine()

### Community 124 - "_FakeEngine"
Cohesion: 0.17
Nodes (11): _FakeEngine, Blocks in backfill_embeddings until stop_event is set or 10s elapses. When…, Fix D: when the fallback thread survives the join timeout, engine.shutdown()…, Fix A: when scheduler shutdown does not complete in time, engine.shutdown()…, Positive path: both fallback and scheduler exit cleanly → engine.shutdown()…, council R1: with the always-on worker, start_session_watcher returns a non-…, test_engine_closed_when_both_exit_cleanly(), test_engine_not_closed_when_fallback_alive() (+3 more)

### Community 125 - "TestConfigureLlm"
Cohesion: 0.22
Nodes (5): Remove known API keys from env so provider setup sees no key., Selecting Anthropic without a key keeps server-side LLM disabled., Selecting OpenAI without a key keeps server-side LLM disabled., Opt-in stores key policy but never the API key value., TestConfigureLlm

### Community 126 - "TestClaudeCodeWirePluginGuard"
Cohesion: 0.21
Nodes (5): A stale enabled flag must not cost the user the whisper., Deliberate: the CLI hooks are global and serve every other project., Fail-open: an unparseable config must not silently disable the whisper., Working plugin, no CLI wiring ever done — the guard is idempotent., TestClaudeCodeWirePluginGuard

### Community 127 - "TestShouldRewind"
Cohesion: 0.18
Nodes (7): ADR-0003: rewind only on NO forward progress; an orphan-with-progress is…, The #149 byte pattern: end_turn boundary, then an assistant 'API Error' record…, A genuine legacy cursor parked mid-response: orphan AND no forward progress., No-progress alone (in-flight tail) must not rewind — only orphan+no-progress…, ADR-0003 large-orphan variant: a giant orphan fragment before the first user…, ADR-0003 accepted-loss pinning (council R1, Cursor+Codex): a GENUINE legacy…, TestShouldRewind

### Community 128 - "test_mcp_adapter.py"
Cohesion: 0.26
Nodes (8): _FakeStdioServer, asyncio, test_call_tool_connect_error_recommends_supervised_start(), test_dispatch_polls_until_phase1_batches_are_ready(), test_dispatch_polls_until_phase2_apply_completes(), test_dispatch_submit_feedback_includes_whisper_log_id(), test_dispatch_uses_extended_timeout_for_maintenance(), test_run_mcp_stdio_generates_session_id_and_runs_server()

### Community 129 - "MemoryEngine"
Cohesion: 0.03
Nodes (48): is_maintenance_due_signal(), Shared wording for the agent-backed maintenance whisper signal., Return true for the current signal line and the legacy bare marker., MemoryEngine, Any, datetime, Delete a memory node from disk and index. Returns confirmation or None., Soft-delete a node only if ``guard(conn)`` still holds inside the write txn.… (+40 more)

### Community 130 - "TestRecallFloorAndSpaceOrdering"
Cohesion: 0.30
Nodes (5): Deliberate recall: wider pool, space scores before the cut, relevance floor…, Cross-space noise penalized below the floor is dropped, not padded., A current-space match outside the old `limit` window survives the cut., A newer other-space node must NOT outrank an older current-space node., TestRecallFloorAndSpaceOrdering

### Community 131 - "TestWhisperDebugMode"
Cohesion: 0.23
Nodes (6): _make_node(), mock_graph(), fixture, Tests for _return_debug mode on build_whisper_context., Nodes that don't clear the injection gate should not appear in injected_ids., TestWhisperDebugMode

### Community 132 - "TestStopOffsetCeiling"
Cohesion: 0.20
Nodes (7): ADR-0004 Task 3: ``stop_offset`` is an ABSOLUTE hard ceiling — no turn is…, Byte offset after the first ``upto`` records, matching ``_write_jsonl``'s…, The flagged leak: ``max_conversation_chars`` commits an oversized FIRST turn…, Everything closed at or before the ceiling is committed; the first turn that…, The non-nudge lane passes ``stop_offset=None`` and must parse exactly as before., The ceiling must also clamp the Codex ``task_complete`` closure site, not only…, TestStopOffsetCeiling

### Community 133 - "ProtectionOperationCoordinator"
Cohesion: 0.40
Nodes (10): ProtectionOperationCoordinator, ProtectionOperation, _result(), test_coordinator_bounds_finished_history(), test_coordinator_redacts_unexpected_exception_details(), test_coordinator_returns_immediately_and_deduplicates_active_work(), test_startup_ignores_non_running_or_uninitialized_stores(), test_startup_resume_failure_never_blocks_server_start() (+2 more)

### Community 134 - "test_embed_node_rows.py"
Cohesion: 0.18
Nodes (7): Tests for MemoryEngine._embed_node_rows (extracted embedding core, #32)., An upsert_batch error is a JOB failure, not a per-node encode failure: it must…, A hard interrupt mid-encode must leave already-encoded chunks persisted, not…, stop_event set mid-run: everything encoded so far is persisted (the final flush…, test_embed_node_rows_flushes_pending_on_cooperative_cancel(), test_embed_node_rows_persists_incrementally(), test_persistence_failure_propagates_not_marked_failed()

### Community 136 - "test_eval_recall/test_report.py"
Cohesion: 0.38
Nodes (8): _make_aggregate(), _make_case_results(), test_format_report_contains_metrics(), test_format_report_shows_regression(), test_format_report_shows_worst_cases(), test_format_report_suppresses_noise(), test_write_results_appends_history(), test_write_results_creates_files()

### Community 137 - "_make_eval_result"
Cohesion: 0.40
Nodes (4): _make_eval_result(), _make_result(), Tests for eval/whisper/report.py., TestFormatReport

### Community 138 - "TestClaudeCodeIsWired"
Cohesion: 0.27
Nodes (4): Regression: the hooks branch read entry.get("command") off the matcher dict, so…, The plugin provides the hooks and MCP server; without this the UI would report…, Nothing would actually fire — reporting 'wired' would be a lie., TestClaudeCodeIsWired

### Community 139 - "test_file_cache.py"
Cohesion: 0.27
Nodes (9): _make_node(), MemoryNode, Tests for FileStore in-memory ID-to-path cache., If the cached path no longer exists, _find_file still finds via glob., test_cache_cleared_on_delete(), test_cache_hit_on_load(), test_cache_populated_on_save(), test_full_cache_build_finds_all_nodes() (+1 more)

### Community 141 - "test_local_auth.py"
Cohesion: 0.20
Nodes (3): parametrize, Tests for the owner-only local admin capability., test_loopback_dependency_accepts_only_local_peers()

### Community 143 - "test_cloud_crypto.py"
Cohesion: 0.20
Nodes (3): Tests for age encryption wrappers., Bundles encrypted pre-rotation must decrypt with the full identity list., test_multi_identity_decrypt_after_rotation()

### Community 144 - "test_cloud_store_lock.py"
Cohesion: 0.27
Nodes (5): _hold_store_lock(), _slow_upload_update(), test_store_lock_is_owner_only_and_blocks_another_process(), test_two_process_state_updates_preserve_both_writers(), _verify_update()

### Community 145 - "setup.py"
Cohesion: 0.05
Nodes (87): info(), ok(), Section header: \\n==> msg (bold)., In-progress: [..] msg (bold brackets)., Success: [ok] msg (green)., Warning: [!!] msg (yellow)., step(), warn() (+79 more)

### Community 146 - "TestExtractionSchema"
Cohesion: 0.20
Nodes (5): confidence:0.0 is a legitimate, falsy value — must survive the `is None` check…, Regression: a memory 'content' that quotes a ```-fenced code block must not…, The fallback (`result`) extraction path is not --json-schema-constrained, so a…, content:null hits the same crash mode as the other three fields:…, TestExtractionSchema

### Community 148 - "test_eval_recall/test_seeder.py"
Cohesion: 0.33
Nodes (9): eval_engine(), _make_case(), fixture, test_clear_removes_all_nodes(), test_seed_after_clear_gives_fresh_state(), test_seed_forces_node_id(), test_seed_indexes_embedding(), test_seed_inserts_nodes_with_correct_ids() (+1 more)

### Community 149 - "test_proposal_claims_investigation.py"
Cohesion: 0.39
Nodes (8): _backdate(), _mk(), Empirical verification of the claims in docs/pr31-lifecycle-proposal.md.…, test_decay_brackets_the_29h_threshold(), test_initial_stability_knob_never_reaches_new_nodes(), test_issue_123_reindex_drops_incoming_edges(), test_purge_is_origin_blind_and_satellite_snapshots_survive(), test_soft_delete_is_invisible_to_search()

### Community 150 - "llm_client.py"
Cohesion: 0.04
Nodes (60): LLMAdapter, Abstract base class for LLM adapters., Send *prompt* to the LLM and return the raw response text. Returns ``None`` on…, Interface that all LLM backends must implement., aborted(), begin_cancel(), begin_lifespan(), epoch_changed() (+52 more)

### Community 152 - "settings"
Cohesion: 0.22
Nodes (9): settings(), account_paths(), fixture, test_logout_still_clears_locally_when_client_construction_fails(), cloud_paths(), fixture, Point every cloud path at tmp and return the key path., test_cloud_init_writes_signed_in_email_to_recovery_kit() (+1 more)

### Community 153 - "test_admin_embedding_backfill_task.py"
Cohesion: 0.22
Nodes (5): embedding_backfill must be a registered admin task in the sleep-cycle (#32)., C1/I1: a failed task yields status=degraded AND HTTP 503 (not 200)., Happy path stays a plain dict (HTTP 200) with status=completed., test_run_all_tasks_completed_returns_dict_when_all_ok(), test_run_all_tasks_degraded_returns_503_when_a_task_raises()

### Community 156 - "test_watermark.py"
Cohesion: 0.22
Nodes (3): Tests for the shared seq-watermark helpers (#81)., Mass reindex re-allocates seq; every incremental cursor must be cleared…, test_full_rebuild_resets_all_incremental_watermarks()

### Community 157 - "test_hybrid_search_raw_cosine.py"
Cohesion: 0.33
Nodes (6): _make_hybrid(), _make_node(), Unit tests for the raw_cosine absolute-signal contract in HybridSearch. The…, A node found only via FTS (no vector hit) must carry no raw_cosine., A node with a genuine vector measurement keeps its raw_cosine., TestRawCosineContract

### Community 158 - "GraphIndex"
Cohesion: 0.05
Nodes (39): batch_fetch_affinity(), compute_affinity_boost(), ndarray, Affinity boost module for the adaptive feedback loop. Computes per-node score…, Fetch all affinity rows for a list of node_ids in a single query. Returns a…, Compute the affinity boost for a candidate node. For each affinity row, a…, ContextBuilder, _find_review_candidate() (+31 more)

### Community 159 - "test_archived_at.py"
Cohesion: 0.36
Nodes (8): _archived_at(), A metadata edit (no tier change) must not move the clock., archival → working → archival must reset the clock, not keep the old one., test_demotion_to_archival_stamps_archived_at(), test_leaving_archival_clears_archived_at(), test_metadata_edit_while_archival_keeps_archived_at(), test_non_archival_update_does_not_stamp(), test_re_entering_archival_restamps_fresh()

### Community 160 - "TestWhisperFailSilently"
Cohesion: 0.22
Nodes (4): Whisper should return empty string on failure, not dump everything., Prompts of 2 chars or less (e.g. 'y', 'ok') should return empty., Prompts of 3+ chars should proceed normally., TestWhisperFailSilently

### Community 161 - "test_eval_recall/test_runner.py"
Cohesion: 0.28
Nodes (6): eval_engine(), _make_case(), fixture, Tests for eval/recall/runner.py., test_run_eval_case_isolation(), test_run_eval_returns_result()

### Community 163 - "_monkeypatch_run_embedding_backfill"
Cohesion: 0.22
Nodes (8): _monkeypatch_run_embedding_backfill(), _QuickEngine, Completes immediately with no missing nodes., Patch run_embedding_backfill to delegate to…, CRB: 8 threads racing _start_backfill_fallback must produce exactly 1 live…, CR1 reverted: handle is always cleared after stop, even on quick completion., test_concurrent_start_creates_single_thread(), test_stop_clears_handle()

### Community 165 - "_write_turns"
Cohesion: 0.25
Nodes (8): A single turn bigger than the budget can't make empty progress — commit it as…, Primary production trigger: an ACTIVE (non-idle) session with MULTIPLE closed…, An active session whose total closed content stays below flush_chars never gets…, test_ingest_session_active_multiturn_below_flush_chars_defers(), test_ingest_session_active_session_flushes_when_over_flush_chars(), test_parse_transcript_no_budget_preserves_behavior(), test_parse_transcript_single_oversized_turn_commits_anyway(), _write_turns()

### Community 167 - "FileStore"
Cohesion: 0.06
Nodes (33): Result of restoring a memory backup., RestoreResult, apply_identity_space_invariants(), _embedding_text(), _generate_title(), Update a memory node. Returns formatted confirmation or None., Embed the given node rows into the vector store. Encode and upsert are…, Identity (about_self) memories are always global: force space=None + lock so no… (+25 more)

### Community 168 - "test_delete_guarded.py"
Cohesion: 0.46
Nodes (6): _archival(), _exists(), A +feedback row inserted inside the guard's txn is visible to the guard's…, test_guard_false_aborts_deletion(), test_guard_observes_writes_in_same_transaction(), test_guard_true_deletes()

### Community 169 - "_FlakyEncoder"
Cohesion: 0.29
Nodes (4): _FlakyEncoder, Tests for _index_embedding bounded retry (#32)., Fails `fail_times` then succeeds, returning a fixed-dim vector., test_index_embedding_retries_then_succeeds()

### Community 170 - "TestExplorationCEGate"
Cohesion: 0.25
Nodes (5): Exploration slot should skip candidates the CE strongly rejected., Candidate with CE < -8 should not be explored even with no affinity signal., Candidate with CE > -8 should still be eligible for exploration., When a candidate has no cross_encoder_score (e.g., reranker errored), the CE…, TestExplorationCEGate

### Community 171 - "test_eval_recall/test_corpus.py"
Cohesion: 0.32
Nodes (3): test_load_golden_case(), test_load_skips_header(), _write_jsonl()

### Community 172 - "test_db_concurrency.py"
Cohesion: 0.36
Nodes (7): _init_db(), Concurrency tests for the thread-local Database connection model., Regression: vec0 module is loaded per connection; a fresh thread must still be…, A read on thread B returns promptly while thread A holds a write tx., test_each_thread_gets_distinct_connection(), test_read_during_write_does_not_block(), test_vector_search_works_from_worker_thread()

### Community 174 - "run.sh"
Cohesion: 0.43
Nodes (5): fail(), ok(), PATH, run.sh script, step()

### Community 175 - "_RecordingDB"
Cohesion: 0.38
Nodes (4): The all-nodes write in importance_scorer must commit in bounded chunks., _RecordingDB, test_commit_updates_chunked_empty(), test_commit_updates_chunked_splits_into_batches()

### Community 176 - "test_embedding_backfill.py"
Cohesion: 0.29
Nodes (3): Tests for the embedding_backfill reconciliation job (#32)., An interrupted run (stop_event set) leaves missing>0, triggering RuntimeError., test_run_embedding_backfill_accepts_stop_event()

### Community 177 - "test_legacy_backfill.py"
Cohesion: 0.57
Nodes (6): _legacy_archival(), _meta_done(), A node whose FILE lacks archived_at (remember(tier=archival) never stamps it)., test_backfill_skipped_when_disabled(), test_backfill_stamps_legacy_files_and_survives_rebuild(), test_backfill_write_failure_preserves_file_and_retries()

### Community 179 - "_FakeEngine"
Cohesion: 0.29
Nodes (6): _FakeEngine, Records the char length of every content payload sent to ingestion., A flush that drains the whole closed delta (sub-cap) must not re-schedule —…, An active (non-idle) session below flush_chars defers (TRANSIENT), then flushes…, test_ingest_session_active_small_session_defers(), test_ingest_session_subcap_flush_does_not_retrigger()

### Community 180 - "test_whisper_log_cleanup.py"
Cohesion: 0.38
Nodes (4): _event(), Tests for normalized whisper payload retention., test_cleanup_deletes_only_stale_unreferenced_rejections(), test_cleanup_is_bounded_and_idempotent()

### Community 181 - "server_manager.py"
Cohesion: 0.05
Nodes (51): CalledProcessError, _cmd_server_start(), Thread-safe message change., Background thread: render braille animation., Animated braille spinner with elapsed time display. Usage:: with…, Spinner, _called_process_error_output(), _find_manual_server_pids() (+43 more)

### Community 182 - "Path"
Cohesion: 0.05
Nodes (56): _candidate_project_roots(), _claude_code_is_wired(), _claude_code_plugin_provides_hooks(), _claude_code_wire(), configure_pi_extension(), _detect_claude_plugin_scope(), _discover_transcripts(), _enabled_plugin_keys() (+48 more)

### Community 183 - "TestIngestConfidence"
Cohesion: 0.29
Nodes (4): Auto-ingested memories should default to confidence=0.7., If the LLM specifies confidence, it should be used., dry_run results should include the confidence value., TestIngestConfidence

### Community 184 - "test_recall_concurrency.py"
Cohesion: 0.33
Nodes (6): Concurrency regression: recall must be safe when routes run in the threadpool.…, engine.graph.conn must resolve to the calling thread's own connection., Hammering recall_search from many threads must not raise (shared-conn race)., _remember(), test_concurrent_recall_does_not_raise(), test_graph_conn_is_per_thread()

### Community 187 - "test_main.py"
Cohesion: 0.29
Nodes (3): parametrize, Tests for the FastAPI app shell., test_local_admin_failure_disables_only_sensitive_routes()

### Community 189 - "cli_adapter.py"
Cohesion: 0.07
Nodes (53): _api(), _client(), cmd_ingest(), cmd_ingest_session(), cmd_node(), cmd_outdated(), cmd_recall(), cmd_remember() (+45 more)

### Community 190 - "backup.py"
Cohesion: 0.08
Nodes (39): BackupError, BackupInfo, BackupService, _count_backupable_markdown(), _count_markdown(), _directory_size(), _infer_user_node_id(), _is_system_self_node() (+31 more)

### Community 191 - "_tool_heavy_turns"
Cohesion: 0.33
Nodes (6): Raw bytes >> cleaned chars. See 01-content-budget.md for why plain-text padding…, A multi-turn slice must never exceed the conversation budget — break BEFORE…, Review I-2: max_raw_bytes has to actually reach parse_transcript through…, test_ingest_session_raw_budget_caps_independently_of_flush_chars(), test_parse_transcript_breaks_before_overshooting_the_content_budget(), _tool_heavy_turns()

### Community 192 - "memory_engine.py"
Cohesion: 0.07
Nodes (36): Automatic space/cluster assignment for unassigned nodes., Assign unassigned nodes to spaces based on their connections., run_auto_cluster(), _apply_edge(), Record a link decision: write to auto_link_checked and optionally create an…, FSRS retrievability-based tier demotion for stale working memories., _ingest_adapter_baseline_timeout(), _prompt_exceeds_provider_capacity() (+28 more)

### Community 193 - "TestSessionBufferRoute"
Cohesion: 0.33
Nodes (4): Tests for the per-session prompt buffer in the whisper route., Buffer should accumulate prompts per session., Different session IDs should have independent buffers., TestSessionBufferRoute

### Community 194 - "test_migration_seq.py"
Cohesion: 0.33
Nodes (5): Tests for nodes.seq column migration and backfill., Regression: a pre-seq DB must migrate without 'no such column: seq'.…, Existing nodes get a monotonic seq ordered by created ASC., test_init_schema_migrates_legacy_db_without_seq(), test_seq_column_backfilled_by_created()

### Community 195 - "_CancellableEngine"
Cohesion: 0.33
Nodes (4): _CancellableEngine, Loops checking stop_event; records whether it received it., stop_event is forwarded to the engine; handle is cleared; saw_stop is True., test_stop_cancels_long_backfill_within_join()

### Community 196 - "test_soft_delete_tombstone.py"
Cohesion: 0.73
Nodes (5): _make(), _store(), test_list_deleted_returns_id_and_deleted_at(), test_purge_removes_tombstone(), test_soft_delete_stamps_deleted_at()

### Community 197 - "SessionHandler"
Cohesion: 0.07
Nodes (32): _configured_watch_roots(), _default_acceptance_roots(), _expand_watch_dir(), _is_nested_or_equal(), _is_subagent_transcript(), _load_state(), FileSystemEventHandler, Path (+24 more)

### Community 199 - "scheduler.py"
Cohesion: 0.06
Nodes (34): BackgroundScheduler, Auto-demote working nodes whose FSRS retrievability drops below threshold., run_decay(), Vector-store reconciliation job: backfill missing embeddings (#32)., Reconcile the vector store. Raises if the store is left incomplete. Unlike the…, run_embedding_backfill(), _commit_updates_chunked(), Background job: recompute importance scores for all memory nodes. (+26 more)

### Community 200 - "test_scheduler_embedding_backfill.py"
Cohesion: 0.40
Nodes (3): The embedding_backfill job must be registered with a post-bind first run (#32)., C2: start_scheduler deve injetar o stop_event no job embedding_backfill., test_scheduler_passes_stop_event_to_embedding_backfill()

### Community 201 - "test_conflict_edge_and_confidence_survive_full_rebuild"
Cohesion: 0.50
Nodes (4): Investigation 2026-08-02 (Parte 2.3): does a conflict edge + a changed…, Create A/B, let conflict_detector.run_conflict_detection write a 'contradicts'…, _reset_adapter(), test_conflict_edge_and_confidence_survive_full_rebuild()

### Community 202 - "test_embedding_observability.py"
Cohesion: 0.60
Nodes (4): stats() must expose the embedding gap + schema version, and recovery must prove…, _set_schema_current(), test_e2e_gap_recovers_via_registered_job(), test_stats_exposes_embedding_gap_and_version()

### Community 203 - "mock_hybrid"
Cohesion: 0.40
Nodes (5): mock_hybrid(), mock_hybrid_blended(), fixture, HybridSearch with blending enabled (default settings)., HybridSearch with mocked internals — no real DB or encoder.

### Community 204 - "main.py"
Cohesion: 0.06
Nodes (40): BaseHTTPMiddleware, FastAPI, load_or_create_local_admin_token(), Path, Owner-only capability authentication for sensitive local API routes., Load this installation's local API capability, creating it mode 0600., AgentMiddleware, Request (+32 more)

### Community 205 - "test_prompt_classifier.py"
Cohesion: 0.33
Nodes (3): Tests for the embedding-based prompt intent classifier., TestContinuationIntent, TestPromptIntent

### Community 206 - "test_real_claude_json_schema_recovers_prose_json_fallback"
Cohesion: 0.50
Nodes (4): skipif, Consolidator-style prompt: known to answer in a single text turn…, test_real_claude_json_schema_recovers_prose_json_fallback(), test_real_claude_json_schema_returns_structured_output()

### Community 208 - "test_ingest_session_drain_continuation_self_triggers"
Cohesion: 0.50
Nodes (4): A JSONL transcript whose closed content is well over flush_chars (60000)., Production wiring: a cap-limited flush calls on_defer_active so the retry Timer…, test_ingest_session_drain_continuation_self_triggers(), _write_big_backlog()

### Community 211 - "routes_agent.py"
Cohesion: 0.11
Nodes (45): connect(), delete_node(), FeedbackRequest, get_maintenance_status(), _maintenance_manager(), MaintenanceRequest, mark_outdated(), MarkOutdatedBody (+37 more)

### Community 212 - "test_tier_manager.py"
Cohesion: 0.50
Nodes (3): Tests for the tier manager., With cap=2 and 3 core nodes, the least-important one should be demoted., test_enforce_core_cap_demotes_least_important()

### Community 213 - "mcp_adapter.py"
Cohesion: 0.06
Nodes (38): AsyncClient, LogRecord, _coerce_list(), create_mcp_server(), _dispatch(), _format_maintenance_batches(), _format_timeout_error(), _handle_error() (+30 more)

### Community 214 - "_reset_deprecation_warn_once"
Cohesion: 0.67
Nodes (3): fixture, The warning is once-per-process, so without this reset the SECOND deprecation…, _reset_deprecation_warn_once()

### Community 215 - "_no_default_acceptance_roots"
Cohesion: 0.67
Nodes (3): _no_default_acceptance_roots(), fixture, D8: the real ~/.claude/projects and ~/.codex/sessions exist on the dev machine,…

### Community 216 - "_insert_node"
Cohesion: 0.09
Nodes (25): _insert_node(), _make_node_dict(), mock_graph(), fixture, Tests for the review mechanism in build_whisper_context., was_injected=0 row within 7 days returns a candidate dict., Node with both was_injected=0 and was_injected=1 within 7 days is excluded., Tests for the Python-side filtering in _find_review_candidate. (+17 more)

### Community 220 - "routes_protection.py"
Cohesion: 0.11
Nodes (41): backup_now(), bind_intent(), _cached_entitlement(), cancel_intent(), confirm_recovery_kit(), _coordinator(), create_intent(), disable_protection() (+33 more)

### Community 227 - "VectorStore"
Cohesion: 0.07
Nodes (26): HybridSearch, _is_question_query(), Any, Hybrid search combining FTS5 + vector search with Reciprocal Rank Fusion. Uses…, Detect whether a query is a natural language question., Fuse multiple ranked lists using weighted Reciprocal Rank Fusion. Each list…, Combines FTS5 full-text search with sqlite-vec vector search., Hybrid search with Reciprocal Rank Fusion. ``query_vec`` may be supplied by a… (+18 more)

### Community 235 - "cli.py"
Cohesion: 0.11
Nodes (39): main(), Entry point for MCP stdio server., _backup_service(), _backup_to_dict(), _cloud_client(), _cmd_account_login(), _cmd_account_logout(), _cmd_account_status() (+31 more)

### Community 236 - "protection.py"
Cohesion: 0.11
Nodes (34): PortalHandoff, _cloud_error_code(), _EnablePrerequisiteError, _finalize_is_definitively_expired(), _known_state(), datetime, Shared encrypted cloud-backup and restore-verification orchestration., Return whether replacing a failed finalize cannot create a duplicate snapshot. (+26 more)

### Community 237 - "ProtectionOperation"
Cohesion: 0.10
Nodes (31): ConfirmRecoveryKitRequest, BaseModel, Optional exact recovery point to verify., Proof from the trusted native save/reopen flow., Purpose-bound response containing no recovery material or locations., Secret-free readiness result for the native save dialog., RecoveryKitPrepareResponse, RecoveryReadinessResponse (+23 more)

### Community 238 - "Database"
Cohesion: 0.09
Nodes (20): compute_whisper_health(), datetime, Whisper effectiveness metrics derived from whisper_log + affinity. Read-only…, Return whisper coverage/precision over all_time and last_7d windows. ``now`` is…, _window(), Database, Path, Insert one prompt payload shared by its candidate log rows. (+12 more)

### Community 239 - "test_account_billing_routes.py"
Cohesion: 0.09
Nodes (23): bound_intent_state(), build_client(), client(), fake_client(), FakeCloudClient, fixture, parametrize, Tests for local account-linked billing handoffs. (+15 more)

### Community 240 - "_seed_similar_nodes"
Cohesion: 0.07
Nodes (14): Tests for the run_maintenance two-call protocol., Create n nodes with similar content and return their IDs., Issue #90 council R4: the finders fail INDEPENDENTLY (distinct queries, no…, A failing batch must block Phase 2's stamp, even though Phase 1 itself no…, No failures -> batch_errors == {}, no meta marker, and Phase 2 stamps…, A recovered system (finder works again) must stop being blocked — the next…, No signal when claude_maintenance_enabled=False., No signal when maintenance was run within the interval. (+6 more)

### Community 241 - "_make_settings_mock"
Cohesion: 0.07
Nodes (23): _make_settings_mock(), Create a MagicMock settings object with affinity-related float attributes., Affinity boost rescues candidates that would otherwise be gated out., A candidate below the injection gate that receives a strong affinity boost…, Affinity boost is only applied when reranker_enabled=True., If affinity boost raises, the pipeline should continue with unmodified scores., A strong negative affinity boost should push a marginal candidate below the…, Exploration slot injects one unconfirmed gated-out candidate. (+15 more)

### Community 242 - "test_scoring_signals.py"
Cohesion: 0.08
Nodes (29): _make_node(), fixture, Tests for recency, access frequency, and tier scoring signals in hybrid search., A core node should outrank an archival node with the same base score., Boosts should not override a large relevance gap. RRF base scores are small…, Build a minimal node dict with scoring-relevant fields., Going from 0→5 accesses should give a larger boost than 15→20., With all boosts set to 0, ranking should match pure fusion. (+21 more)

### Community 243 - "IngestSpool"
Cohesion: 0.09
Nodes (22): IngestSpool, Path, Durable ingest queue built from directory entries (ADR-0004 Amendment…, Enqueue a job. The boundary lives in the filename: a second, slower nudge for…, Claim the oldest due pending job. The rename IS the mutual exclusion. ⚠️ This…, Mark a job done. Idempotent: completing an already-completed job must not…, Return a claimed job to pending/, or dead-letter it, keyed on failure CLASS --…, Move a job to failed/ WITH its original bytes -- never unlink without first… (+14 more)

### Community 244 - "hippocampus.py"
Cohesion: 0.11
Nodes (28): _detect_space(), _file_hash(), HippocampusHandler, _ingest_file(), _load_state(), _matches_ignore(), FileSystemEventHandler, Observer (+20 more)

### Community 245 - "account.py"
Cohesion: 0.12
Nodes (30): AccountError, AccountStatus, _close_owned(), CodeRequestResult, get_account_status(), logout_account(), LogoutResult, _map_cloud_error() (+22 more)

### Community 246 - "billing.py"
Cohesion: 0.12
Nodes (29): BaseException, NoReturn, BillingError, BillingOffer, _canonical_account_id(), _canonical_uuid4(), CheckoutHandoff, CheckoutStatus (+21 more)

### Community 247 - "forgetting_manager.py"
Cohesion: 0.13
Nodes (31): _archival_rows(), _aware(), _backfill_legacy_archived_at(), _cap_guard(), _connectivity(), _eligibility_guard(), _evaluate_protection(), _forget_score() (+23 more)

### Community 248 - "bundle.py"
Cohesion: 0.11
Nodes (30): _add_member(), build_bundle(), BundleError, BundleInfo, _check_dest(), _iter_bundle_files(), _member_allowed(), open_bundle() (+22 more)

### Community 270 - "state.py"
Cohesion: 0.16
Nodes (26): _as_utc(), cloud_status_payload(), CloudStateLoadError, _ensure_writable_schema(), _existing_store_id(), _legacy_protection_state(), load_state(), mutate_state() (+18 more)

### Community 289 - "StoreLock"
Cohesion: 0.13
Nodes (16): Path, RuntimeError, Validate the canonical kit and confirm a reopened native saved copy., Validate the fixed canonical kit without changing readiness., Repair a stale canonical kit before a native save operation. Returns ``True``…, Record a saved-copy proof only when its bytes equal the current valid kit., Clear readiness before installing a recovery-first key rotation. The ordering…, Raised when recovery material cannot be proven current and complete. (+8 more)

### Community 290 - "parse_transcript"
Cohesion: 0.13
Nodes (25): _assistant_is_terminal(), _coerce_entry(), _conversation_from_turns(), _extract_assistant_text(), extract_user_prompts(), _extract_user_text(), _format_turn(), _is_bootstrap_user_text() (+17 more)

### Community 291 - "get_fastembed_cache_dir"
Cohesion: 0.13
Nodes (20): get_fastembed_cache_dir(), get_model_cache_dirname(), is_model_cached(), Path, Helpers for locating and inspecting the shared Ormah model cache., Return the effective shared model cache directory., Resolve a fastembed model name to its on-disk cache directory name., Return True when the model's expected fastembed cache directory exists. (+12 more)

### Community 292 - "test_cloud_state.py"
Cohesion: 0.13
Nodes (15): CloudState, test_cloud_state_json_contains_only_plain_metadata(), test_cloud_status_derives_paused_when_upload_entitlement_ends(), test_cloud_status_derives_stale_and_verification_warnings(), test_cloud_status_exposes_only_derived_recovery_readiness(), test_cloud_status_exposes_pollable_intent_without_account_binding(), test_cloud_status_never_reports_protected_when_invariant_is_incomplete(), test_cloud_status_reports_uploaded_snapshot_awaiting_verification() (+7 more)

### Community 293 - "_install_hooks"
Cohesion: 0.09
Nodes (22): _codex_agents_target(), _codex_wire(), configure_claude_hooks(), configure_codex_hooks(), _enable_codex_feature(), install_claude_agents(), install_codex_agents(), install_codex_md() (+14 more)

### Community 294 - "synthetic_pattern_monitor.py"
Cohesion: 0.15
Nodes (19): find_rotted_patterns(), live_patterns(), _proposed_action(), datetime, Detect synthetic-prompt patterns that stopped matching (#143). The #134…, Stable text derived ONLY from the pattern — this string is the dedup key. Never…, Propose corrections for synthetic patterns that went quiet (#143). Proposes,…, A live pattern that matched before and has now gone quiet. (+11 more)

### Community 295 - "entitlements.py"
Cohesion: 0.21
Nodes (18): _as_utc(), cache_entitlements(), check_entitlement(), EntitlementCache, EntitlementStatus, load_entitlement_cache(), Any, datetime (+10 more)

### Community 296 - "restore.py"
Cohesion: 0.16
Nodes (19): CloudRestoreError, CloudRestoreResult, _committed_blobs(), _existing_store_id(), Any, Path, RuntimeError, Reusable cloud snapshot discovery and full restore workflow. (+11 more)

### Community 297 - "consolidator.py"
Cohesion: 0.13
Nodes (15): _apply_consolidation(), _cluster_signature(), _consolidate_cluster(), _find_consolidation_clusters(), Background job: consolidate clusters of similar working-tier memories via LLM., Create a consolidated node, link originals, and demote them to archival.…, Find clusters of similar working memories and consolidate via LLM., Consolidate a single cluster using LLM summarization. (+7 more)

### Community 298 - "test_cloud_recovery.py"
Cohesion: 0.11
Nodes (6): fixture, parametrize, Path, recovery_store(), test_unversioned_or_unsupported_kit_cannot_be_confirmed(), test_wrong_store_key_or_kit_fails_closed()

### Community 299 - "MaintenanceManager"
Cohesion: 0.18
Nodes (10): MaintenanceJob, MaintenanceManager, Any, Exception, Background execution manager for agent-driven maintenance., In-memory state for a single maintenance run., Run maintenance phases in background threads with single-flight semantics., Start phase 1 if needed, or return the existing job state. (+2 more)

### Community 300 - "_find_binary"
Cohesion: 0.11
Nodes (18): _claude_code_detected(), _claude_desktop_wire(), _codex_detected(), configure_claude_code_mcp(), configure_claude_desktop(), configure_codex_mcp(), _find_binary(), _merge_json_file() (+10 more)

### Community 301 - "pair_batch.py"
Cohesion: 0.16
Nodes (15): _bisect(), build_batch_prompt(), _diagnostic_pair_id(), _judge_chunk(), _judge_singles(), parse_batch_verdicts(), Any, Batch judgment of candidate pairs — shared by the pairwise maintenance jobs… (+7 more)

### Community 302 - "get"
Cohesion: 0.13
Nodes (15): get_clients(), get_insights(), get_proposals(), list_audit_log(), list_merges(), get, List all supported agents with detection and wired status. Returns a list of…, Get belief evolutions and conflicting ideas detected by the system. (+7 more)

### Community 303 - "routes_ui.py"
Cohesion: 0.19
Nodes (14): get_graph(), get_insights(), get_node_detail(), get, Request, UI API routes for the web graph explorer., Search nodes for the UI, returning structured results. Uses the same hybrid…, Graph data for the explorer. Default (no ``space``): the *active graph* — non-… (+6 more)

### Community 304 - "routes_ingest.py"
Cohesion: 0.23
Nodes (13): ConversationLog, ingest_conversation(), ingest_file(), ingest_nudge(), NudgeRequest, BaseModel, post, Request (+5 more)

### Community 305 - "prompt_classifier.py"
Cohesion: 0.19
Nodes (9): extract_time_params(), PromptClassifier, PromptIntent, Embedding-based intent classifier for whisper-inject prompts., Parse lightweight time references and return…, Result of classifying a user prompt., Classify prompt intent using cosine similarity to archetype embeddings. Lazy-…, Classify *prompt* and return an intent with search-param overrides. (+1 more)

### Community 306 - "NodeFileHandler"
Cohesion: 0.19
Nodes (9): NodeFileHandler, callable, FileSystemEventHandler, Observer, Path, File system watcher for memory node changes., Watches memory/nodes/ for file changes and triggers re-indexing., Start watching the nodes directory for changes. (+1 more)

### Community 307 - "HTTPException"
Cohesion: 0.17
Nodes (13): delete, HTTPException, Request, Reject sensitive requests that did not originate on this machine., Authenticate a native local caller without exposing the cloud account token., require_local_admin(), require_loopback(), Wire ormah into a single agent by id. (+5 more)

### Community 308 - "console.py"
Cohesion: 0.22
Nodes (9): fail(), play_finale(), Shared output formatting for CLI and setup — matches install.sh visual style., Stop spinner and print [ok] final line., Play a ~2.5s terminal animation: 'ormah' dissolves into a sphere. TTY only —…, Reset color detection cache (for testing)., Error: [xx] msg (bold, to stderr)., _reset_color_cache() (+1 more)

### Community 309 - "EmbeddingAdapter"
Cohesion: 0.24
Nodes (7): EmbeddingAdapter, ndarray, Interface that all embedding backends must implement., Encode a single text string to a normalized vector., Encode a batch of texts to normalized vectors., Encode a search query. Override to add model-specific query prefixes., Return the dimensionality of the embedding vectors.

### Community 310 - "relevance_quarantine.py"
Cohesion: 0.24
Nodes (10): iter_dropped(), prompt_version(), Path, quarantine_path(), Durable, append-only quarantine ledger for memories dropped by the relevance…, Path to the quarantine JSONL file, beside the store DB (settings.db_path)., First 12 hex chars of sha256 of the ingest LLM rules prompt text., Append one dropped-candidate record to the quarantine ledger. *mode* is… (+2 more)

### Community 311 - "format_node_with_neighbors"
Cohesion: 0.36
Nodes (10): _excerpt(), _feedback_id_suffix(), format_node(), format_node_with_neighbors(), format_search_results(), Any, Format graph data as human/agent-readable text., Format a single node as readable text. (+2 more)

### Community 312 - "store_lock.py"
Cohesion: 0.36
Nodes (8): canonical_memory_dir(), _entry_for(), _LockEntry, Path, Cross-process lock for operations that act on one local memory store., Return the stable local identity used for locking one memory directory., Return the lock path without consulting cloud enrollment or ``store_id``., store_lock_path()

### Community 313 - "embeddings/__init__.py"
Cohesion: 0.27
Nodes (5): Abstract base class for embedding adapters., Embedding adapter package — pluggable backends for vector encoding., LiteLLM embedding adapter — supports OpenAI, Gemini, Voyage, Mistral, etc., Local fastembed embedding adapter (CPU-only, no PyTorch/CUDA required)., Ollama embedding adapter — calls /api/embed endpoint.

### Community 314 - "jobs.py"
Cohesion: 0.31
Nodes (7): Guarded scheduler adapters for shared cloud protection operations., Run one scheduled backup, swallowing every exception at the scheduler boundary., Run weekly verification, swallowing every exception at the scheduler boundary., run_cloud_backup(), run_restore_verification(), Return a useful error without returning or logging credential-bearing material., safe_error_message()

### Community 315 - "LocalAdapter"
Cohesion: 0.36
Nodes (3): LocalAdapter, ndarray, Wraps fastembed with lazy loading and caching.

### Community 316 - "LiteLLMEmbeddingAdapter"
Cohesion: 0.38
Nodes (3): LiteLLMEmbeddingAdapter, ndarray, Produces embeddings via litellm.embedding().

### Community 317 - "OllamaEmbeddingAdapter"
Cohesion: 0.38
Nodes (3): OllamaEmbeddingAdapter, ndarray, Produces embeddings via a local Ollama instance.

### Community 319 - "settings.py"
Cohesion: 0.50
Nodes (3): persist_settings_delta(), Structured persistence for cloud protection settings., Persist only keys changed by a caller, serialized with every other writer.

### Community 320 - "get_adapter"
Cohesion: 0.50
Nodes (3): Thin cached facade over pluggable embedding adapters., get_adapter(), Build an embedding adapter from the application settings.

## Knowledge Gaps
- **1 isolated node(s):** `PATH`
  These have ≤1 connection - possible missing edges or undocumented components.
- **61 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MemoryEngine` connect `MemoryEngine` to `session_watcher.py`, `IndexBuilder`, `auto_linker.py`, `llm_client.py`, `GraphIndex`, `get_fastembed_cache_dir`, `FileStore`, `consolidator.py`, `MaintenanceManager`, `memory_engine.py`, `.connect`, `SessionHandler`, `scheduler.py`, `main.py`, `routes_agent.py`, `Settings`, `VectorStore`, `ProtectionOperation`, `Database`, `IngestSpool`, `hippocampus.py`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Why does `test_preference_merge_leaves_displaced_candidate_stage_as_candidate()` connect `test_whisper_claims_investigation.py` to `patch`, `Database`?**
  _High betweenness centrality (0.014) - this node is a cross-community bridge._
- **Why does `_make_node_dict()` connect `_make_node_dict` to `TestWhisperFailSilently`, `TestWhisperIntentAware`, `TestExplorationCEGate`, `_insert_node`, `TestWhisperContextBuffer`, `TestWhisperRerankerBlendIntegration`, `_make_settings_mock`, `TestWhisperDecisions`, `TestWhisperTopicShift`, `test_whisper_context.py`, `._builder`?**
  _High betweenness centrality (0.012) - this node is a cross-community bridge._
- **Are the 504 inferred relationships involving `patch` (e.g. with `test_detect_fallback_to_cwd_basename()` and `test_detect_from_git_repo()`) actually correct?**
  _`patch` has 504 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `MemoryEngine` (e.g. with `HippocampusHandler` and `MaintenanceJob`) actually correct?**
  _`MemoryEngine` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `Settings` (e.g. with `HybridSearch` and `MemoryEngine`) actually correct?**
  _`Settings` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `PATH` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._