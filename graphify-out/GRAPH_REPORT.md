# Graph Report - ormah  (2026-08-12)

## Corpus Check
- 686 files · ~896,017 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 8049 nodes · 18153 edges · 345 communities (323 shown, 22 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 1908 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0ca65ba1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- MemoryEngine
- patch
- test_hippocampus.py
- .backup_now
- Tauri Product Bridge
- IngestSpool
- Pi Plugin Client
- CloudProtectionService
- rerank
- memory_engine.py
- Tauri Sidecar Commands
- init_key
- test_config.py
- setup.py
- load_state
- Ingest is async: the client nudges, the server owns the cursor and advances on job completion
- CloudRecoveryPreflightError
- timedelta
- Web UI Graph View
- Settings
- routes_agent.py
- protection.py
- Claude CLI Adapter
- check_entitlement
- CloudState
- routes_account.py
- session_watcher.py
- test_conflict_detector.py
- BackupService
- test_session_watcher_flush.py
- llm_client.py
- test_eval_whisper/test_metrics.py
- test_duplicate_merger.py
- JobTracker
- llm/__init__.py
- CreateNodeRequest
- Tauri Bundle Config
- test_whisper_out.py
- server_manager.py
- ContextBuilder
- open_bundle
- routes_protection.py
- EmbeddingAdapter
- run_importance_scoring
- CLI Adapter Tests
- test_whisper_context.py
- api
- routes_admin.py
- run_setup
- ormah/cli.py
- ui src App
- billing.py
- backup.py
- _insert_node
- test_main_lifespan_shutdown.py
- FileStore
- ProtectionPanel
- dependencies
- ok
- IndexBuilder
- cli_adapter.py
- config.py
- test ingest
- HybridSearch
- run_uninstall
- PromptIntent
- test_spreading_activation.py
- TestClient
- CloudError
- ProtectionOperationCoordinator
- test_ingest_extraction.py
- test_eval_recall/test_metrics.py
- test cleanup auto ingested
- run_auto_linker
- compute_affinity_boost
- Database
- test merge undo
- test seq fingerprint
- test_init_vec_table_guard.py
- test feedback schema
- _make_titled_hybrid
- get_fastembed_cache_dir
- test_auto_linker.py
- validate_case
- run forgetting
- reset_adapter
- recall/cli.py
- test pair batch
- src types
- CloudClient
- TestSafeBoundary
- run_whisper_eval
- forgetting manager
- _is_ormah_hook
- run_setup_json
- TestSubmitFeedbackBasic
- test relevance runner
- _NeverEofProc
- get_ormah_bin_path
- parse_transcript
- test_mutation_stamping.py
- start_scheduler
- mine
- db.py
- test_routes.py
- desktop ui package
- consolidator.py
- conflict_detector.py
- Connection
- test_server_manager.py
- .demote
- context_builder.py
- parser.py
- setup_logging
- crypto.py
- test_backup.py
- extract_time_params
- TestConsolidationSignatureSkip
- _insert_injected_whisper_log
- PromptClassifier
- mcp_adapter.py
- compilerOptions
- background/__init__.py
- seed case
- test_hybrid_search.py
- test_eval_recall/test_report.py
- run_decay
- compute whisper health
- compilerOptions
- desktop ui src App
- restore.py
- detect_space_from_cwd
- cloud/__init__.py
- MemoryEngine facade
- APScheduler background scheduler
- seed_case
- format_report
- _FakeEngine
- load_corpus
- run_eval
- test_main_backfill_fallback.py
- Whisper pipeline (involuntary recall)
- configure_codex_mcp
- _create_pair
- _edges_between
- transfer.py
- run_embedding_backfill
- test_account_auth_routes.py
- test_stats.py
- test_cloud_cli.py
- visual
- _find_link_candidates
- test_routes_graph.py
- configure_claude_code_mcp
- conftest.py
- test cli account
- TestSyntheticPromptEndpoint
- Ormah Desktop (Tauri v2 app)
- TestReleaseVersionVerification
- scenario
- ORMAH  settings and .env load order
- test_audit_log.py
- whisper/runner.py
- compilerOptions
- run_auto_cluster
- normalize_link_type
- test llm cancel
- extract_json
- load_corpus
- set_cloud_backup_enabled
- _claude_code_wire
- test_protection_routes.py
- test_scoring_signals.py
- configure_claude_hooks
- test parser
- forceLayout
- permissions
- graph
- _write_env_file
- configure_codex_hooks
- llm_cancel.py
- MaintenanceManager
- VectorStore
- match synthetic pattern
- _sanitize_fts_query
- _claude_code_plugin_provides_hooks
- get_watermark
- _node_dict
- UpdateNodeRequest
- Desktop release build job (macOS + Linux matrix)
- HybridSearch pipeline
- CloudProtectionService (reusable owner of backup now and res
- Force-Directed Graph Canvas (full-bleed)
- cmd_eval_whisper_run
- main.py
- .generate
- should rewind
- Reconciling #126 (pair-verdict invalidation) with #208 (lock-order hoist) in IndexBuilder
- TestGetMaintenanceBatches
- test graph
- ormah setup wizard
- graph
- routes ingest
- test_routes_admin_run_task.py
- LocalAdapter
- OllamaEmbeddingAdapter
- TestCliEntryPoint
- _run_fusion
- logging_setup.py
- Path
- NodeFileHandler
- test_run_stats.py
- LiteLLMEmbeddingAdapter
- constants
- GraphCanvas
- pi-plugin package
- test mcp adapter
- TestWhisperSignal
- Suppressing selection with a fact, not with the cursor (ADR-0004)
- strip temporal phrases
- _remove_mcp_from_json
- TestMarkOutdated
- TestWhisperFailSilently
- test_miner.py
- Canonical Ormah guidance block (Claude memory file)
- run whisper log cleanup
- safe_error_message
- TestWhisperDecisions
- SessionHandler
- Global Constraints
- install_claude_md
- key_path
- TestRecallFloorAndSpaceOrdering
- ._run_uninstall_with_mem_dir
- whisper/cli.py
- TestStopOffsetCeiling
- GraphView component (Cytoscape rendering + selection)
- test tool schemas
- ormah/__init__.py
- relevance quarantine
- do install
- validate_llm_runtime_config
- account.py
- TestStopRunningServer
- generate_server_wrapper
- Ormah Desktop App Icon (canonical 512px master)
- renderer
- Encoder factory (get encoder   get adapter)
- Ormah system map
- age encryption envelope (client-side, private identity never
- TestSpaceScoring
- FakeProtectionService
- top2_recall
- TestWhisperIdentityGating
- hatch build
- Ormah Project Banner Image
- Canonical ormah-maintenance agent (mcp  ormah  run maintenan
- Ormah Claude Code plugin (manifest, hooks, MCP, commands)
- TestExtractionSchema
- test_hybrid_search_raw_cosine.py
- .search
- proposals.py
- _reciprocal_rank_fusion
- test delete guarded
- single instance listener
- peerDependencies
- install
- devDependencies
- peerDependenciesMeta
- keywords
- run
- test legacy backfill
- injection_precision
- test_live_drain_recovers_a_job_stranded_in_running
- Any
- test recall concurrency
- InsightsPanel
- build
- verify release versions
- files
- test_adapters.py
- `frozen_until` Implementation Plan — Overview
- test soft delete tombstone
- test graph focus
- has_false_positive
- Whisper golden corpus (golden golden.jsonl, local-only)
- test graph drag
- test graph layout
- NodeDetail
- repository
- pair skip
- CI test job
- ormah
- scripts
- no default acceptance roots
- TestSessionBufferRoute
- run_mcp_stdio
- test graph cluster
- build-sidecar
- ormah-mcp
- ormah-whisper-inject
- ormah-whisper-store
- text   init
- 01-suppression-fact.md
- TestIngestConfidence
- 02-reconcile-gate.md
- 03-enqueue-path-gate.md
- ormah
- 04-shrink-reset-clears.md
- 05-verify-and-merge.md
- test_migration_seq.py
- _upload_due
- test_low_confidence_penalized_more
- test_length_penalty_disabled_at_zero
- test_keyword_query_still_uses_title_boost

## God Nodes (most connected - your core abstractions)
1. `Settings` - 212 edges
2. `MemoryEngine` - 185 edges
3. `CreateNodeRequest` - 147 edges
4. `ContextBuilder` - 144 edges
5. `CloudProtectionService` - 125 edges
6. `Database` - 112 edges
7. `load_state()` - 93 edges
8. `parse_transcript()` - 89 edges
9. `_make_node_dict()` - 85 edges
10. `_mark_idle()` - 75 edges

## Surprising Connections (you probably didn't know these)
- `Pi ormah-maintenance agent prompt (ormah_run_maintenance)` --semantically_similar_to--> `Shipped ormah-pi-maintenance agent prompt`  [INFERRED] [semantically similar]
  integrations/pi-plugin/agents/ormah-maintenance.md → src/ormah/agents/ormah-pi-maintenance.md
- `Claude plugin ormah-maintenance agent` --semantically_similar_to--> `Canonical ormah-maintenance agent (mcp__ormah__run_maintenance)`  [INFERRED] [semantically similar]
  integrations/claude-plugin/agents/ormah-maintenance.md → src/ormah/agents/ormah-maintenance.md
- `Shipped ormah-maintenance slash command` --semantically_similar_to--> `/ormah:maintenance command`  [INFERRED] [semantically similar]
  src/ormah/commands/ormah-maintenance.md → integrations/claude-plugin/commands/maintenance.md
- `Case-design rules (labels precede runs, >=6 memories, named distractors)` --semantically_similar_to--> `Maintenance decision rules (honest none, submit all evaluated pairs)`  [INFERRED] [semantically similar]
  eval/whisper/corpus/README.md → src/ormah/agents/ormah-maintenance.md
- `_make_engine()` --calls--> `MemoryEngine`  [INFERRED]
  eval/recall/cli.py → src/ormah/engine/memory_engine.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Cloud protection pipeline: local snapshot, manifest, age envelope, presigned PUT, immutable promotion, restore rehearsal** — docs_15___cloud_backup__verification__and_restore_local_backup, docs_15___cloud_backup__verification__and_restore_bundle_manifest, docs_15___cloud_backup__verification__and_restore_age_encryption, docs_15___cloud_backup__verification__and_restore_presigned_url, docs_15___cloud_backup__verification__and_restore_immutable_promotion, docs_15___cloud_backup__verification__and_restore_restore_verification, docs_15___cloud_backup__verification__and_restore_upload_journal [EXTRACTED 1.00]
- **Desktop release supply chain (version guard, sidecar, signing, updater feed)** — _github_workflows_desktop_release_version_guard, _github_workflows_desktop_release_uv_sidecar_download, _github_workflows_desktop_release_apple_notarization, _github_workflows_desktop_release_updater_feed, desktop_readme_bundled_runtime [EXTRACTED 1.00]
- **Icon composition: dark tile + tan ring + glowing teal node** — desktop_src_tauri_icons_icon_appicon, desktop_src_tauri_icons_icon_darktile, desktop_src_tauri_icons_icon_orbitring, desktop_src_tauri_icons_icon_glowingnode, desktop_src_tauri_icons_icon_colorpalette [EXTRACTED 1.00]
- **Banner composition: wordmark + teal orb accent over starfield backdrop** — docs_banner_ormahwordmark, docs_banner_tealorbglyph, docs_banner_starfieldbackdrop, docs_banner_projectbanner [EXTRACTED 1.00]
- **Graph explorer chrome: wordmark + search + node count over a full-bleed canvas** — docs_graph_ormahwordmark, docs_graph_searchinput, docs_graph_nodecountreadout, docs_graph_forcedirectedcanvas [EXTRACTED 1.00]
- **Sleep-cycle maintenance batch** — docs_05___background_jobs_importance_scorer, docs_05___background_jobs_duplicate_merger, docs_05___background_jobs_conflict_detector, docs_05___background_jobs_auto_linker, docs_05___background_jobs_auto_cluster, docs_05___background_jobs_consolidator, docs_05___background_jobs_decay_manager [EXTRACTED 1.00]
- **Two-call run_maintenance protocol shared across Claude, Pi, and shipped agents** — integrations_claude_plugin_agents_ormah_maintenance_maintenance_agent, integrations_pi_plugin_agents_ormah_maintenance_pi_maintenance_agent, src_ormah_agents_ormah_maintenance_maintenance_agent, src_ormah_agents_ormah_pi_maintenance_pi_maintenance_agent, src_ormah_commands_ormah_maintenance_maintenance_command, integrations_claude_plugin_commands_maintenance_ormah_maintenance_command, integrations_claude_plugin_agents_ormah_maintenance_two_call_protocol [EXTRACTED 1.00]
- **Whisper precision stack (retrieve, rerank, boost, filter, gate)** — docs_03___search_and_ranking_hybrid_search, docs_06___embeddings_system_reranker, docs_09___affinity_and_feedback_affinity, docs_04___whisper___involuntary_recall_topical_overlap_filter, docs_04___whisper___involuntary_recall_injection_gate [EXTRACTED 1.00]
- **Visual encoding of the memory graph: nodes, edges, color, and lens layout** — docs_graph_memorynodes, docs_graph_memoryedges, docs_graph_colorencodingscheme, docs_graph_lensclusterlayout [INFERRED 0.85]
- **Per-agent Ormah guidance blocks installed by ormah setup (Claude, Codex, Pi)** — src_ormah_instructions_ormah_guidance_block, src_ormah_codex_instructions_codex_guidance_block, src_ormah_pi_instructions_pi_guidance_block, integrations_claude_plugin_setup_claude_md_install [INFERRED 0.95]

## Communities (345 total, 22 thin omitted)

### Community 0 - "MemoryEngine"
Cohesion: 0.03
Nodes (54): apply_identity_space_invariants(), MemoryEngine, Any, datetime, MemoryNode, Update a memory node. Returns formatted confirmation or None., Delete a memory node from disk and index. Returns confirmation or None., Soft-delete a node only if ``guard(conn)`` still holds inside the write txn.… (+46 more)

### Community 1 - "patch"
Cohesion: 0.03
Nodes (152): patch, _file_hash(), _ingest_session(), Return SHA-256 hex digest of a file's contents., Ingest a single JSONL session transcript if changed. ``boundary`` is the…, _append_assistant(), _append_codex_turn(), _append_pair() (+144 more)

### Community 2 - "test_hippocampus.py"
Cohesion: 0.05
Nodes (58): _detect_space(), _file_hash(), HippocampusHandler, _ingest_file(), _load_state(), _matches_ignore(), FileSystemEventHandler, Observer (+50 more)

### Community 3 - ".backup_now"
Cohesion: 0.09
Nodes (38): BackupInfo, ProtectionState, _backup_for_upload(), _backup_matches_memory(), _cleared_upload_journal(), _cloud_error_code(), _existing_store_id(), _finalize_is_definitively_expired() (+30 more)

### Community 4 - "Tauri Product Bridge"
Cohesion: 0.09
Nodes (69): account_status(), AccountStatus, backup_now(), billing_offer(), BillingOffer, bind_protection_intent(), cancel_protection_intent(), CheckoutHandoff (+61 more)

### Community 5 - "IngestSpool"
Cohesion: 0.04
Nodes (60): IngestSpool, Path, Durable ingest queue built from directory entries (ADR-0004 Amendment…, Enqueue a job. The boundary lives in the filename: a second, slower nudge for…, Claim the oldest due pending job. The rename IS the mutual exclusion. ⚠️ This…, Mark a job done. Idempotent: completing an already-completed job must not…, Return a claimed job to pending/, or dead-letter it, keyed on failure CLASS --…, Move a job to failed/ WITH its original bytes -- never unlink without first… (+52 more)

### Community 6 - "Pi Plugin Client"
Cohesion: 0.05
Nodes (41): ormahPi(), IngestBody, MaintenanceResults, OrmahClient, OrmahHttpError, RecallBody, RememberBody, WhisperResponse (+33 more)

### Community 7 - "CloudProtectionService"
Cohesion: 0.09
Nodes (70): Build a BackupService from a Settings-like object., service_from_settings(), CloudProtectionService, Reusable cloud protection operations constructed from application settings., cloud_state_dir(), FakeCloudClient, _patch_upload_prerequisites(), _patch_verification() (+62 more)

### Community 8 - "rerank"
Cohesion: 0.05
Nodes (44): Rerank search results using a cross-encoder with linear-rescale blended…, rerank(), _candidate(), _linear_rescale(), Unit tests for the cross-encoder reranker with linear-rescale blended scoring.…, blend_alpha=1 means only CE matters., Verify min_score threshold applies to blended score., Build a minimal search result dict. (+36 more)

### Community 9 - "memory_engine.py"
Cohesion: 0.04
Nodes (90): FSRS retrievability-based tier demotion for stale working memories., Central facade for all memory operations., # NOTE: index_single calls _remove_node internally which wipes edges,, Tier promotion/demotion and core cap enforcement., Manages tier transitions and enforces the core memory cap., TierManager, The ingest extraction prompt contract: rules, response schema, rendered…, EdgeType (+82 more)

### Community 10 - "Tauri Sidecar Commands"
Cohesion: 0.06
Nodes (58): Command, base_url(), detect_agents(), fetch_stats(), graph_url(), is_onboarded(), mark_onboarded(), marker_path() (+50 more)

### Community 11 - "init_key"
Cohesion: 0.06
Nodes (68): _atomic_write_0600(), current_recipient(), _ensure_recovery_kit_can_be_rewritten(), extract_recovery_kit_format_version(), extract_store_id(), get_or_create_store_id(), import_key(), init_key() (+60 more)

### Community 12 - "test_config.py"
Cohesion: 0.05
Nodes (69): parametrize, Tests for config validation., Create settings with overrides, using a temp dir for memory_dir., council C2: constructing Settings must NEVER raise for this pair — `ormah…, _settings(), test_activation_decay_one_ok(), test_activation_decay_zero(), test_affinity_defaults() (+61 more)

### Community 13 - "setup.py"
Cohesion: 0.04
Nodes (70): _candidate_project_roots(), _claude_code_detected(), _codex_agents_target(), _codex_detected(), configure_pi_extension(), _detect_claude_plugin_scope(), _enable_codex_feature(), _enabled_plugin_keys() (+62 more)

### Community 14 - "load_state"
Cohesion: 0.09
Nodes (59): load_state(), Load one store's state, distinguishing absence from unsafe existing data., Update selected fields while preserving the rest of one store's state., update_state(), cloud_state_dir(), FakeClient, fixture, parametrize (+51 more)

### Community 15 - "Ingest is async: the client nudges, the server owns the cursor and advances on job completion"
Cohesion: 0.06
Nodes (31): A deleted transcript is classed as an external failure, against the contract, Accepted cost, Amendment 2026-07-22 — the durable queue is a directory spool, not the Cursor alone (and not a job table), Amendment 2026-07-28 — slice 3: the frozen tail is force-closed automatically, behind an anti-rewind checkpoint, Amendment 2026-08-09 — the 2026-07-28 force-close REMEDY is retracted; its DIAGNOSIS is confirmed and still open, Amendment 2026-08-10 — the cause is found: the frozen-prefix jump is a WINDOWED-parse artefact, Amendment 2026-08-11 — H1's "retry forever" has a hard stop at attempt 1025, and a deleted transcript never reaches the dead-letter, Amendment 2026-08-12 — the windowed-parse defect reproduces post-wipe; neither fix from 08-09/08-10 has shipped (+23 more)

### Community 16 - "CloudRecoveryPreflightError"
Cohesion: 0.04
Nodes (38): CloudRecoveryPreflightError, _codex_unwire(), _pi_unwire(), RuntimeError, Remove Ormah agent definitions from ~/.codex/agents/., Remove ormah whisper hooks from ~/.codex/hooks.json., Remove ormah whisper hooks from ~/.claude/settings.json., Remove the ormah instructions block from ~/.pi/agent/AGENTS.md. (+30 more)

### Community 17 - "timedelta"
Cohesion: 0.06
Nodes (68): find_rotted_patterns(), live_patterns(), _proposed_action(), datetime, Detect synthetic-prompt patterns that stopped matching (#143). The #134…, Stable text derived ONLY from the pattern — this string is the dedup key. Never…, Propose corrections for synthetic patterns that went quiet (#143). Proposes,…, A live pattern that matched before and has now gone quiet. (+60 more)

### Community 18 - "Web UI Graph View"
Cohesion: 0.05
Nodes (45): FIT_PADDING_RATIO, fitToNodes(), MIN_FIT_RATIO, NOTE: the relative-ratio step assumes camera.angle === 0 (no rotation). This…, FakeOpts, Framed, Pt, BANNER_BTN_STYLE (+37 more)

### Community 19 - "Settings"
Cohesion: 0.06
Nodes (6): BaseSettings, field_validator, True when an LLM provider is configured (not ``"none"``)., Settings, test_scheduler_registers_cloud_backup_and_weekly_verification(), TestGetAdapter

### Community 20 - "routes_agent.py"
Cohesion: 0.07
Nodes (61): delete, connect(), delete_node(), FeedbackRequest, get_clients(), get_insights(), get_maintenance_status(), get_proposals() (+53 more)

### Community 21 - "protection.py"
Cohesion: 0.05
Nodes (72): ConfirmRecoveryKitRequest, BaseModel, Optional exact recovery point to verify., Proof from the trusted native save/reopen flow., Purpose-bound response containing no recovery material or locations., Secret-free readiness result for the native save dialog., RecoveryKitPrepareResponse, RecoveryReadinessResponse (+64 more)

### Community 22 - "Claude CLI Adapter"
Cohesion: 0.07
Nodes (55): ClaudeCliAdapter, _fake_popen(), _pid_alive(), integration, skipif, Belt-and-suspenders against the real binary: an operator SessionStart hook must…, Belt-and-suspenders against the real binary: a prompt asking to read a probe…, Consolidator-style prompt: known to answer in a single text turn… (+47 more)

### Community 23 - "check_entitlement"
Cohesion: 0.17
Nodes (19): cache_entitlements(), check_entitlement(), Any, Return ``active|grace|expired|none`` without propagating refresh failures., Atomically cache the raw server response plus its fetch timestamp., cache_path(), FakeClient, Exception (+11 more)

### Community 24 - "CloudState"
Cohesion: 0.08
Nodes (55): _state_after_verification(), _as_utc(), cloud_status_payload(), CloudState, _ensure_writable_schema(), _existing_store_id(), is_device_loss_recovery_ready(), is_protected_and_verified() (+47 more)

### Community 25 - "routes_account.py"
Cohesion: 0.11
Nodes (37): account_checkout(), _account_http_error(), account_logout(), account_offer(), account_portal(), account_request_code(), account_status(), account_verify_code() (+29 more)

### Community 26 - "session_watcher.py"
Cohesion: 0.03
Nodes (126): The one spool-root path every caller must use -- never reach for /tmp. The…, A short stable hash identifying one watch root's spool. Roots must not share a…, root_key(), spool_root(), Re-admit new LLM calls after a RECOVERABLE cancel (the watcher's startup…, resume_llm_adapters(), _assistant_response_after_prompt(), _confidence() (+118 more)

### Community 27 - "test_conflict_detector.py"
Cohesion: 0.07
Nodes (57): _conflict_scope_value(), _find_conflict_candidates(), Find node pairs that might contradict each other. ``delta=False`` (default —…, Find potentially contradicting nodes and create edges. Seeds are delta-selected…, run_conflict_detection(), _conflict_response(), _create_pair(), _make_belief() (+49 more)

### Community 28 - "BackupService"
Cohesion: 0.13
Nodes (13): BackupService, datetime, Creates, lists, prunes, and restores local memory file backups., Create a timestamped backup, serialized across in-process jobs., Create a timestamped backup of source-of-truth memory files., Return backups newest first., Return the newest backup, if one exists., Return True when there is no backup or the newest one is too old. (+5 more)

### Community 29 - "test_session_watcher_flush.py"
Cohesion: 0.04
Nodes (42): _FakeConn, fixture, Presence detection must not fire on a commented-out line or on a longer key…, Review M-9: the repo owner's ordered fix (warn instead of silently `continue`…, Regression for review F1: with no ~/.config/ormah/.env and no ./.env,…, The F1 fix must not over-correct into swallowing a REAL read failure…, Council R1 (Cursor): a floor of `>= flush_chars` compares bytes to chars and…, Raw bytes >> cleaned chars. See 01-content-budget.md for why plain-text padding… (+34 more)

### Community 30 - "llm_client.py"
Cohesion: 0.12
Nodes (20): _get_or_create_ingest_adapter(), ingest_llm_generate(), ingest_provider_configured(), Shared LLM facade for background tasks. All callers import ``llm_generate``…, Ingest path: PROPAGATE LlmCancelledError. The engine maps it to a provider-wide…, True when a server-side extraction adapter is available (ingest provider !=…, _resolve_ingest_model(), _resolve_ingest_provider() (+12 more)

### Community 31 - "test_eval_whisper/test_metrics.py"
Cohesion: 0.13
Nodes (12): compute_prompt_metrics(), f1_score(), injection_recall(), Metrics for whisper eval: injection recall, precision, f1, top2_recall,…, For noise cases: True if pipeline correctly stayed silent. None for non-noise., Fraction of should_inject nodes that appeared in injected output., suppression_correct(), Tests for eval/whisper/metrics.py. (+4 more)

### Community 32 - "test_duplicate_merger.py"
Cohesion: 0.08
Nodes (53): Find near-duplicate nodes and create merge proposals. Uses a multi-signal…, run_duplicate_detection(), _create_pair(), _duplicate_response(), _make_fact(), Tests for LLM-based duplicate consolidation in duplicate_merger., With llm_provider='none', LLM is never called., For medium-confidence pairs, proposal contains merged content preview. (+45 more)

### Community 33 - "JobTracker"
Cohesion: 0.08
Nodes (38): JobTracker, Track background job execution status for observability., Wrap a job function with tracking. Returns a no-arg callable for the scheduler., Thread-safe registry of background job execution outcomes., Yield True if this caller claimed the job, False if it was already running. An…, tracked(), MaintenanceJob, Background execution manager for agent-driven maintenance. (+30 more)

### Community 34 - "llm/__init__.py"
Cohesion: 0.08
Nodes (35): LLMAdapter, Abstract base class for LLM adapters., Send *prompt* to the LLM and return the raw response text. Returns ``None`` on…, Interface that all LLM backends must implement., Claude CLI LLM adapter — headless `claude -p` via subscription auth (no paid…, _get_or_create_adapter(), get_adapter(), LLM adapter package — pluggable backends for background jobs. (+27 more)

### Community 35 - "CreateNodeRequest"
Cohesion: 0.03
Nodes (75): _embedding_text(), _generate_title(), Generate a short title from the first line/sentence of content., Build text for embedding. Truncates content to avoid topic averaging in long…, CreateNodeRequest, An edge another writer already created must not raise., test_conflict_edge_write_is_idempotent(), consolidation_engine() (+67 more)

### Community 36 - "Tauri Bundle Config"
Cohesion: 0.04
Nodes (46): app, security, windows, withGlobalTauri, build, beforeBuildCommand, frontendDist, bundle (+38 more)

### Community 37 - "test_whisper_out.py"
Cohesion: 0.08
Nodes (29): _concurrent_appender(), _concurrent_drainer(), _isolate_cache(), _make_transcript(), _mock_client(), _outbox_records(), fixture, skipif (+21 more)

### Community 38 - "server_manager.py"
Cohesion: 0.07
Nodes (39): CalledProcessError, _called_process_error_output(), _find_manual_server_pids(), install_autostart(), install_launchd_agent(), install_systemd_service(), is_first_run(), _is_ormah_server_start_command() (+31 more)

### Community 39 - "ContextBuilder"
Cohesion: 0.03
Nodes (62): ContextBuilder, Builds agent context from core memories., _make_node_dict(), _make_settings_mock(), Whisper formatting: flat list, top 2 full, rest title-only., Underspecified follow-up prompts should use recent context in search., Topic-shift detection: skip injection when prompt is on the same topic., High similarity to recent prompts → skip whisper. (+54 more)

### Community 40 - "open_bundle"
Cohesion: 0.07
Nodes (61): _add_member(), build_bundle(), BundleError, BundleInfo, _check_dest(), _iter_bundle_files(), _member_allowed(), open_bundle() (+53 more)

### Community 41 - "routes_protection.py"
Cohesion: 0.11
Nodes (41): backup_now(), bind_intent(), cancel_intent(), confirm_recovery_kit(), _coordinator(), create_intent(), disable_protection(), EmptyRequest (+33 more)

### Community 42 - "EmbeddingAdapter"
Cohesion: 0.11
Nodes (16): EmbeddingAdapter, ndarray, Abstract base class for embedding adapters., Interface that all embedding backends must implement., Encode a single text string to a normalized vector., Encode a batch of texts to normalized vectors., Encode a search query. Override to add model-specific query prefixes., Return the dimensionality of the embedding vectors. (+8 more)

### Community 43 - "run_importance_scoring"
Cohesion: 0.07
Nodes (35): _commit_updates_chunked(), Background job: recompute importance scores for all memory nodes., Apply (importance, node_id) updates in bounded write transactions so a full-…, Iterate all nodes, compute weighted importance, persist changes., run_importance_scoring(), The all-nodes write in importance_scorer must commit in bounded chunks., _RecordingDB, test_commit_updates_chunked_empty() (+27 more)

### Community 44 - "CLI Adapter Tests"
Cohesion: 0.08
Nodes (44): _mock_response(), Tests for the CLI adapter., Run the CLI with given args, returning (exit_code, stdout, stderr)., Create a mock httpx.Response., When cwd is missing, space should be None (no space key in body)., Nudge appears at the Nth prompt (default 10)., Nudge never appears when interval is 0., Each session_id gets its own counter. (+36 more)

### Community 45 - "test_whisper_context.py"
Cohesion: 0.07
Nodes (21): _make_engine_with_encoder(), Tests for whisper context (involuntary recall injection)., Standing rules use a typed applicability channel without biasing facts., Create a mock engine with a hybrid search encoder that returns a fixed vector., The injection gate cuts absolute signals (ce_absolute / raw_cosine), never the…, A weak query's least-bad match: blended ~0.9 (rank-relative top) but the cross-…, A genuinely relevant match under-ranked by the bi-encoder: the cross-encoder…, Results carrying neither absolute signal keep pre-contract gate behavior… (+13 more)

### Community 46 - "api"
Cohesion: 0.11
Nodes (39): AdminTask, AgentInfo, BackupInfo, BackupStatus, CloudStatus, createBackup(), del(), fetchAdminTasks() (+31 more)

### Community 47 - "routes_admin.py"
Cohesion: 0.09
Nodes (44): HTTPException, _backup_service_from_request(), backup_status(), _backup_status_payload(), _backup_to_dict(), BackupSettingsUpdate, cloud_status(), create_backup() (+36 more)

### Community 48 - "run_setup"
Cohesion: 0.09
Nodes (28): backfill_transcripts(), configure_llm(), _cost_hint(), _disable_llm(), _enable_llm(), _estimate_cost(), _persist_env_delta(), _print_setup_summary() (+20 more)

### Community 49 - "ormah/cli.py"
Cohesion: 0.10
Nodes (52): cmd_eval_recall_import_labels(), main(), Entry point for MCP stdio server., _backup_service(), _backup_to_dict(), _cloud_client(), _cmd_account_login(), _cmd_account_logout() (+44 more)

### Community 50 - "ui src App"
Cohesion: 0.09
Nodes (32): fetchNodeDetail(), App(), DEFAULT_EDGE_TYPES, Filters, PanelId, ThemeTransitionState, EDGE_TYPES, FilterDrawer() (+24 more)

### Community 51 - "billing.py"
Cohesion: 0.11
Nodes (31): BaseException, NoReturn, BillingError, BillingOffer, _canonical_account_id(), _canonical_uuid4(), CheckoutHandoff, CheckoutStatus (+23 more)

### Community 52 - "backup.py"
Cohesion: 0.16
Nodes (20): BackupError, _count_backupable_markdown(), _count_markdown(), _directory_size(), _infer_user_node_id(), _is_system_self_node(), _parse_backup_created_at(), _parsed_nodes() (+12 more)

### Community 53 - "_insert_node"
Cohesion: 0.10
Nodes (25): _find_review_candidate(), Find a gated-out whisper candidate eligible for session-start review. Applies…, _insert_node(), _make_node_dict(), Tests for the review mechanism in build_whisper_context., was_injected=0 row within 7 days returns a candidate dict., Node with both was_injected=0 and was_injected=1 within 7 days is excluded., Tests for the Python-side filtering in _find_review_candidate. (+17 more)

### Community 54 - "test_main_lifespan_shutdown.py"
Cohesion: 0.07
Nodes (31): _FakeEngine, Blocks in backfill_embeddings until stop_event is set or 10s elapses. When…, _fake_lifespan_deps(), asyncio, fixture, Bounded scheduler shutdown + engine.shutdown() policy (Fix A / Fix D). Tests…, Fix D: when the fallback thread survives the join timeout, engine.shutdown()…, Fix A: when scheduler shutdown does not complete in time, engine.shutdown()… (+23 more)

### Community 55 - "FileStore"
Cohesion: 0.09
Nodes (27): FileStore, MemoryNode, Path, List tombstones in deleted/ as (node_id, deleted_at, path)., Hard-delete a tombstone from deleted/. Returns True if removed. Pass ``path``…, Load all nodes from disk., List all markdown file paths., Compute SHA-256 hash of a file's contents. (+19 more)

### Community 56 - "ProtectionPanel"
Cohesion: 0.09
Nodes (36): errorMessage(), formatDate(), formatPrice(), LoginPurpose, operationIsActive(), operationLabel(), operationSuccessMessage(), phaseIndex() (+28 more)

### Community 57 - "dependencies"
Cohesion: 0.05
Nodes (41): graphology, graphology-layout, graphology-layout-forceatlas2, jsdom, lucide-react, sigma, @tauri-apps/api, dependencies (+33 more)

### Community 58 - "ok"
Cohesion: 0.05
Nodes (30): fail(), ok(), play_finale(), Shared output formatting for CLI and setup — matches install.sh visual style., Thread-safe message change., Stop spinner and print [ok] final line., Background thread: render braille animation., Play a ~2.5s terminal animation: 'ormah' dissolves into a sphere. TTY only —… (+22 more)

### Community 59 - "IndexBuilder"
Cohesion: 0.07
Nodes (30): Connection, Database, FileStore, Path, Row, IndexBuilder, Update index for changed/new files. Returns (added, updated) counts., Index or re-index a single file. (+22 more)

### Community 60 - "cli_adapter.py"
Cohesion: 0.08
Nodes (49): _api(), _client(), cmd_ingest(), cmd_ingest_session(), cmd_node(), cmd_outdated(), cmd_recall(), cmd_remember() (+41 more)

### Community 61 - "config.py"
Cohesion: 0.11
Nodes (16): model_validator, _deprecated_key_present(), Path, Application configuration via environment variables and .env file., True when the deprecated key is set in ANY configured settings source.…, _prompt_exceeds_provider_capacity(), The prompt's ESTIMATED token count when it overflows the usable input window,…, estimated_tokens() (+8 more)

### Community 62 - "test ingest"
Cohesion: 0.06
Nodes (28): _canned(), integration, parametrize, skipif, Tests for conversation ingestion: dry_run, confidence, truncation., Real claude_cli round-trip: mandatory schema must survive an actual `claude -p`…, dry_run=True should return extracted memories without calling remember()., Verify no nodes are created during dry_run. (+20 more)

### Community 63 - "HybridSearch"
Cohesion: 0.08
Nodes (25): HybridSearch, Combines FTS5 full-text search with sqlite-vec vector search., _make_node(), Unit tests for HybridSearch title boost score capping. Verifies that…, Multiple query tokens matching title → high title_bonus, but still capped., Even with tier boost + recency + access, final_score capped at 1.0., Build a minimal node dict matching GraphIndex.get_nodes_batch output., Question queries disable title boost, so no cap needed (but shouldn't break). (+17 more)

### Community 64 - "run_uninstall"
Cohesion: 0.13
Nodes (9): _cloud_recovery_paths(), Return recovery artifacts that uninstall must never delete., Remove Ormah while preserving zero-knowledge cloud recovery material., run_uninstall(), fixture, parametrize, Keep uninstall tests from touching the developer's real Ormah install., Shared patcher helper — not used directly, see individual tests. (+1 more)

### Community 65 - "PromptIntent"
Cohesion: 0.08
Nodes (19): PromptIntent, Result of classifying a user prompt., TestPromptIntent, Precision helpers should favor the most relevant whisper candidate., Context-enhanced search using recent prompts., The reranker must score the same context-enhanced query that search ran on, not…, Fully specified prompts should not be polluted by recent context., Without recent_prompts, search query should be the raw prompt. (+11 more)

### Community 66 - "test_spreading_activation.py"
Cohesion: 0.11
Nodes (38): _excerpt(), _feedback_id_suffix(), format_node(), format_node_with_neighbors(), format_search_results(), Any, Format graph data as human/agent-readable text., Format a single node as readable text. (+30 more)

### Community 67 - "TestClient"
Cohesion: 0.10
Nodes (25): TestClient, bound_intent_state(), build_client(), client(), fake_client(), FakeCloudClient, fixture, parametrize (+17 more)

### Community 68 - "CloudError"
Cohesion: 0.10
Nodes (20): BaseTransport, _client_version(), CloudError, get_or_create_device_id(), Any, Path, RuntimeError, HTTP client and local account identity for the Ormah Cloud service. (+12 more)

### Community 69 - "ProtectionOperationCoordinator"
Cohesion: 0.13
Nodes (20): LocalOperation, ProtectionOperationCoordinator, datetime, ProtectionOperation, Small in-process coordinator for long-running cloud protection operations., Submit work or return the matching operation already in progress., Queue the one durable Protect operation that may survive a process crash.…, Token-free polling record for one local background invocation. (+12 more)

### Community 70 - "test_ingest_extraction.py"
Cohesion: 0.05
Nodes (44): Split content into pieces at line (turn) boundaries; each piece is <=hard_cap.…, _split_for_extraction(), Extraction error classification: timeout/call-failure must not read as 'no…, If every chunk's call fails while a provider is configured, the whole…, Extracted memories below ingest_min_confidence are dropped before node creation., A single line (turn) longer than hard_cap is split into <=hard_cap pieces,…, An oversized turn between normal turns is split without dropping any turn or…, A variable payload against a fixed provider timeout is the bug. The hint must… (+36 more)

### Community 71 - "test_eval_recall/test_metrics.py"
Cohesion: 0.10
Nodes (36): compute_case_metrics(), f1_at_k(), false_negative_rate(), false_positive_present(), mrr(), precision_at_k(), Precision, recall, and related retrieval metrics for recall eval., Compute all metrics for a single (prompt, results) pair. injection_fired: True… (+28 more)

### Community 72 - "test cleanup auto ingested"
Cohesion: 0.13
Nodes (29): main(), _node_source(), plan_cleanup(), _print_table(), Path, Perform the destructive cleanup. Returns a process exit code. Steps:…, run_cleanup(), _FakeBackupService (+21 more)

### Community 73 - "run_auto_linker"
Cohesion: 0.13
Nodes (24): _get_watermark(), Automatic edge creation based on embedding similarity., Render one candidate pair for a batched link prompt (#87)., Return the seq of the last fully-processed node, or 0 if unset., Nodes with seq strictly greater than the watermark, ascending, bounded., Incrementally link nodes with seq above the watermark, judging candidate pairs…, _render_link_pair(), run_auto_linker() (+16 more)

### Community 74 - "compute_affinity_boost"
Cohesion: 0.09
Nodes (23): compute_affinity_boost(), ndarray, Affinity boost module for the adaptive feedback loop. Computes per-node score…, Compute the affinity boost for a candidate node. For each affinity row, a…, _insert_affinity_row(), _make_affinity_db(), _make_vec(), ndarray (+15 more)

### Community 75 - "Database"
Cohesion: 0.05
Nodes (33): Hybrid search combining FTS5 + vector search with Reciprocal Rank Fusion. Uses…, Database, Run migrations for existing databases., Manages per-thread SQLite connections with WAL mode and serialized writes., Add candidate-stage diagnostics without rebuilding feedback history., Record which synthetic pattern fired, so rot detection has a signal (#143)., Normalize prompt payloads without rebuilding exact feedback rows., Recreate FTS table with porter stemmer if it uses the old tokenizer. (+25 more)

### Community 76 - "test merge undo"
Cohesion: 0.08
Nodes (35): _create_node(), Tests for execute_merge and undo_merge operations., When remapping creates a self-loop, the edge is dropped., When remapping would duplicate an existing edge, it's skipped., execute_merge creates a record in merge_history., Undoing a merge restores the removed node., When merging nodes of different tiers, the higher-tier node is kept., Undoing a merge restores the removed node's original edges. (+27 more)

### Community 77 - "test seq fingerprint"
Cohesion: 0.10
Nodes (35): _make_node(), Conditional seq allocation driven by a persisted content fingerprint (#126)., auto_cluster dual-writes `space`: straight into SQLite AND into the markdown., Content feeds the embedding and the judge prompt., Type is shown to the LLM judge., Tags feed FTS, never the linker., A row whose file on disk no longer matches its file_hash has a pending reindex.…, A row whose file matches its hash is stamped, so the upgrade does not requeue… (+27 more)

### Community 78 - "test_init_vec_table_guard.py"
Cohesion: 0.15
Nodes (16): _count(), Guard: a dim mismatch must never silently DROP a populated vector store., An empty table is recreated freely and must not burn the one-shot token., TOCTOU: two concurrent init_vec_table(allow_drop=True) calls against the same…, The consumed-marker must accumulate. A later migration must not erase the…, A node_vectors table whose DDL has no FLOAT[dim] (corrupt/foreign schema) must…, MemoryEngine.__init__ authorizes the drop only when the flag equals the…, A consumed reindex authorization must not silently re-authorize a second… (+8 more)

### Community 79 - "test feedback schema"
Cohesion: 0.11
Nodes (34): _index_exists(), _make_db_without_new_tables(), _make_legacy_affinity_db(), Path, Tests for whisper_log, affinity, and review_log schema additions., Feedback is capped per whisper event, not per whole session., Create a DB, init schema, then drop the three new tables to simulate an older…, Calling _migrate() on an already-migrated DB must not raise. (+26 more)

### Community 80 - "_make_titled_hybrid"
Cohesion: 0.06
Nodes (34): _make_titled_hybrid(), A node with valid_until in the future should not be filtered., With 10 results in both lists, min-max normalization should produce a score…, Two results at adjacent ranks in both lists (spread ~1.6%) should use max-norm…, A single result should use max-norm fallback and score > 0.7., Question query with FTS and vec disagreement — semantic match should still win…, Create a HybridSearch with titled nodes and optional content lengths., A node with the query term in its title scores higher than one with it only in… (+26 more)

### Community 81 - "get_fastembed_cache_dir"
Cohesion: 0.09
Nodes (23): get_fastembed_cache_dir(), get_model_cache_dirname(), is_model_cached(), Path, Helpers for locating and inspecting the shared Ormah model cache., Return the effective shared model cache directory., Resolve a fastembed model name to its on-disk cache directory name., Return True when the model's expected fastembed cache directory exists. (+15 more)

### Community 82 - "test_auto_linker.py"
Cohesion: 0.09
Nodes (30): Tests for LLM-based edge type classification in auto_linker., Pairs already checked should not trigger a second LLM call on re-run., Pairs classified as 'none' should be recorded in auto_link_checked., Re-writing a node's content bumps its seq to the head (crit#2 mechanism)., A direct metadata UPDATE (not via the builder) must not change seq., Updating a node's content should clear its checked pairs so it gets re-…, Issue #90: pairs_evaluated must reflect exactly one LLM decision call. Uses the…, Issue #90 (council finding 2): an LLM-unavailable pair (None decision) must… (+22 more)

### Community 83 - "validate_case"
Cohesion: 0.21
Nodes (3): Validate a single corpus case. Raises CorpusError on structural issues., validate_case(), TestValidateCase

### Community 84 - "run forgetting"
Cohesion: 0.20
Nodes (31): Soft-delete dead-weight archival nodes, then purge expired tombstones., run_forgetting(), _archival_count(), _backdate_tombstone(), _break(), _enable(), _exists(), _make_archival_recent() (+23 more)

### Community 85 - "reset_adapter"
Cohesion: 0.10
Nodes (24): Clear the cached adapters (useful for test isolation)., reset_adapter(), integration, skipif, End-to-end: --json-schema -> structured_output round-trips for the consolidate…, test_real_claude_cli_consolidate_creates_node_with_valid_type(), _concurrent_first_use(), Tests for the shared LLM facade — provider-configured detection. (+16 more)

### Community 86 - "recall/cli.py"
Cohesion: 0.13
Nodes (18): _check_fail_below(), _check_regression(), cmd_eval_recall_export_for_labeling(), cmd_eval_recall_run(), _corpus_files_for_label(), _make_engine(), Path, CLI handlers for `ormah eval recall` commands. (+10 more)

### Community 87 - "test pair batch"
Cohesion: 0.09
Nodes (20): Issue #87: pair batching — settings, timeout hint, batch module., Council R2: zero-usable gets ONE half-size probe, never the full tree., The bound applies to ZERO_USABLE only — unparseable keeps today's tree., Council C1: an outage must not iterate the whole collected list., _settings(), test_batching_settings_defaults(), test_explicit_k_overrides_settings(), test_k1_is_a_pure_map_over_judge_single() (+12 more)

### Community 88 - "src types"
Cohesion: 0.11
Nodes (23): searchNodes(), Props, SearchResults(), PanelId, Props, TopBar(), buildDimmed(), DimmedSets (+15 more)

### Community 89 - "CloudClient"
Cohesion: 0.17
Nodes (28): CloudClient, Small synchronous client for the metadata-only Ormah Cloud API., mock, parametrize, test_auth_and_entitlement_requests_match_service_shapes(), test_client_factory_reads_settings(), test_create_checkout_session_fails_closed_on_malformed_checkout_required(), test_create_checkout_session_handles_non_checkout_statuses() (+20 more)

### Community 90 - "TestSafeBoundary"
Cohesion: 0.06
Nodes (16): safe_* must exclude a dangling user turn; raw fields still include it., tool_use followed by a text assistant must form ONE pair, not fragment. The…, A trailing tool-only assistant (no text) leaves the pair pending (known…, A multi-record assistant response at EOF must not be committed mid-stream. The…, Once the next user turn arrives, the full multi-record response is one safe…, A multi-record response (tool_use then end_turn) is one safe pair, never split…, If the user interrupts a non-terminal response, the next user turn still closes…, A slice that begins with assistant records (a cursor left mid-response by an… (+8 more)

### Community 91 - "run_whisper_eval"
Cohesion: 0.19
Nodes (6): Run the whisper eval pipeline over *cases*., run_whisper_eval(), integration, End-to-end integration coverage for the whisper eval harness., test_run_whisper_eval_end_to_end_with_real_engine(), TestRunWhisperEval

### Community 92 - "forgetting manager"
Cohesion: 0.13
Nodes (29): _archival_rows(), _aware(), _backfill_legacy_archived_at(), _cap_guard(), _connectivity(), _eligibility_guard(), _evaluate_protection(), _forget_score() (+21 more)

### Community 93 - "_is_ormah_hook"
Cohesion: 0.17
Nodes (8): _claude_code_is_wired(), _is_ormah_hook(), True when a hook entry is one Ormah installs (argv-aware, not substring).…, Regression: the hooks branch read entry.get("command") off the matcher dict, so…, The plugin provides the hooks and MCP server; without this the UI would report…, Nothing would actually fire — reporting 'wired' would be a lie., TestClaudeCodeIsWired, TestIsOrmahHook

### Community 94 - "run_setup_json"
Cohesion: 0.12
Nodes (23): AgentDescriptor, configure_agent_maintenance(), detect_clients(), _detected_agents(), _get_agent(), Ask whether to enable automatic agent-backed maintenance. Returns True if…, Legacy flat detection dict — kept for backwards compatibility., Non-interactive agent wiring for the Mac app's one-click setup button. Wires… (+15 more)

### Community 95 - "TestSubmitFeedbackBasic"
Cohesion: 0.10
Nodes (6): _insert_review_log(), _insert_whisper_log(), fixture, Tests for engine.submit_feedback and POST /agent/feedback route., TestSubmitFeedbackBasic, TestSubmitFeedbackRoute

### Community 96 - "test relevance runner"
Cohesion: 0.15
Nodes (24): _default_engine(), _labels_for(), main(), Any, Path, In-context relevance-gate eval (the ship gate). Run pre-merge with a live…, Return the list of provenance labels the real extractor emits for a snippet., Construct the real MemoryEngine the way the codebase does (see… (+16 more)

### Community 97 - "_NeverEofProc"
Cohesion: 0.11
Nodes (4): _FakeProc, _NeverEofProc, A child whose pipes NEVER reach EOF — models the setsid grandchild that…, Minimal fake Popen result. Mirrors real subprocess.Popen semantics closely…

### Community 98 - "get_ormah_bin_path"
Cohesion: 0.11
Nodes (14): get_ormah_bin_path(), Find the absolute path to the ormah binary., _claude_desktop_wire(), _codex_wire(), configure_claude_desktop(), install_codex_agents(), install_codex_md(), Register ormah MCP server in Claude Desktop config (if installed). Returns True… (+6 more)

### Community 99 - "parse_transcript"
Cohesion: 0.16
Nodes (8): parse_transcript(), Parse a supported JSONL transcript into cleaned conversation text. Reads line…, Path, Write a list of dicts as JSONL to a temp file and return the path., A trailing pair with NO completion signal (no stop_reason field) is not safe…, A terminal stop_reason (Claude Code) closes the response immediately — the safe…, TestParseTranscript, _write_jsonl()

### Community 100 - "test_mutation_stamping.py"
Cohesion: 0.18
Nodes (27): _backdate(), _create(), Mutation-stamping guarantees (Sync v1 Step 0). Every content mutation must…, Create a node with auto-linking suppressed, return its id., Phase-2 repaired defines edges must live in the self node's markdown so they…, Parse the tombstone file for a node from deleted/., _reset_adapter(), test_auto_cluster_advances_updated() (+19 more)

### Community 101 - "start_scheduler"
Cohesion: 0.14
Nodes (17): BackgroundScheduler, datetime, Event, APScheduler job registration for background processing., One shared factor for all four jobs, so distinct nominal offsets stay distinct…, First run is offset to spread the LLM jobs, always inside one interval., Register and start all background jobs. Returns ``(scheduler, tracker)`` so the…, _stagger_factor() (+9 more)

### Community 102 - "mine"
Cohesion: 0.15
Nodes (17): _connect_ro(), _draft_expected(), _load_prompt_groups(), mine(), MinerError, Exception, Path, Mine whisper eval cases from the live DB's whisper_log (read-only). Drafted… (+9 more)

### Community 103 - "db.py"
Cohesion: 0.15
Nodes (12): SQLite database connection management., _init_db(), Concurrency tests for the thread-local Database connection model., Regression: vec0 module is loaded per connection; a fresh thread must still be…, A read on thread B returns promptly while thread A holds a write tx., test_each_thread_gets_distinct_connection(), test_read_during_write_does_not_block(), test_vector_search_works_from_worker_thread() (+4 more)

### Community 104 - "test_routes.py"
Cohesion: 0.07
Nodes (18): health(), client(), fixture, Tests for API routes., CH2: with no scheduler, a degraded fallback makes /admin/health degraded., Inverse: a healthy fallback (flag False) leaves health ok., Issue #90 (dev council follow-up): a Phase 1 with a broken finder must still…, CR2: scheduler present + embedding_backfill last run failed -> health degraded. (+10 more)

### Community 105 - "desktop ui package"
Cohesion: 0.07
Nodes (26): dependencies, framer-motion, react, react-dom, devDependencies, @types/react, @types/react-dom, typescript (+18 more)

### Community 106 - "consolidator.py"
Cohesion: 0.10
Nodes (20): _apply_consolidation(), _cluster_signature(), _consolidate_cluster(), _find_consolidation_clusters(), Background job: consolidate clusters of similar working-tier memories via LLM., Create a consolidated node, link originals, and demote them to archival.…, Find clusters of similar working memories and consolidate via LLM., Consolidate a single cluster using LLM summarization. (+12 more)

### Community 107 - "conflict_detector.py"
Cohesion: 0.06
Nodes (41): _llm_check_conflict(), Detect contradictions between memory nodes., Render one candidate pair for a batched conflict prompt (#87)., Ask LLM whether two nodes contradict each other. Returns parsed dict or None if…, _render_conflict_pair(), _composite_score(), _find_merge_candidates(), _llm_check_duplicate() (+33 more)

### Community 108 - "Connection"
Cohesion: 0.12
Nodes (9): Create an edge between two nodes., Path, Insert one prompt payload shared by its candidate log rows., Backfill content_fingerprint for rows whose file on disk hasn't changed. A row…, Drop a dead thread's connection from the registry and close it., Connection, BaseModel, Reindexing a node must not wipe why its edges exist. (+1 more)

### Community 109 - "test_server_manager.py"
Cohesion: 0.07
Nodes (19): Tests for server lifecycle helpers: port-conflict detection and launchd plist., A ThrottleInterval backstops genuine crash loops., A healthy Ormah listener makes a duplicate foreground start a no-op., A foreign listener must make the supervisor retry instead of going dormant., A bound, listening socket is reported as in use., When the port is free, uvicorn is launched as normal., A port with no listener is reported as free., An IPv6 host literal must not fail the pre-flight probe. (+11 more)

### Community 110 - ".demote"
Cohesion: 0.32
Nodes (5): MemoryNode, Promote a node to a higher tier. Returns True if promoted., Demote a node to a lower tier. Returns True if demoted., If core nodes exceed the cap, demote least-accessed ones to working. Nodes in…, Tier

### Community 111 - "context_builder.py"
Cohesion: 0.05
Nodes (32): batch_fetch_affinity(), Fetch all affinity rows for a list of node_ids in a single query. Returns a…, _first_sentence_truncate(), _gate_score(), _has_topical_overlap(), _prompt_log_snippet(), ndarray, Builds whisper context for involuntary recall injection. (+24 more)

### Community 112 - "parser.py"
Cohesion: 0.10
Nodes (25): _assistant_is_terminal(), _coerce_entry(), _conversation_from_turns(), _extract_assistant_text(), extract_user_prompts(), _extract_user_text(), _format_turn(), _is_bootstrap_user_text() (+17 more)

### Community 113 - "setup_logging"
Cohesion: 0.20
Nodes (13): _JSONFormatter, Path, Configure the root logger. Args: log_format: ``"text"`` for human-readable…, Emit one JSON object per log line. Fields: ``ts``, ``level``, ``logger``,…, setup_logging(), Tests for structured logging setup., test_json_formatter_basic(), test_json_formatter_exception() (+5 more)

### Community 114 - "crypto.py"
Cohesion: 0.15
Nodes (28): Identity, Recipient, CloudCryptoError, decrypt_bytes(), encrypt_bytes(), generate_identity(), identity_from_str(), identity_to_str() (+20 more)

### Community 115 - "test_backup.py"
Cohesion: 0.18
Nodes (26): Return and validate the active Self pointer carried by a local backup.…, Create a backup when automatic backups are enabled and due., resolve_backup_user_node_id(), run_auto_backup(), _active_self(), MemoryNode, Path, _save_node() (+18 more)

### Community 116 - "extract_time_params"
Cohesion: 0.16
Nodes (9): extract_time_params(), Parse lightweight time references and return…, Backwards-compatible wrapper around module-level :func:`extract_time_params`., Tests for extract_time_params (bounded time windows)., last 2 weeks' uses rolling previous-period: 4w ago → 2w ago., last 1 week' (N=1) extends to now, not rolling., last 3 months' uses rolling: 6m ago → 3m ago., PromptClassifier._extract_time_params still works. (+1 more)

### Community 117 - "TestConsolidationSignatureSkip"
Cohesion: 0.11
Nodes (8): Tests for the memory consolidation background job., An empty/blank summary is a no-op that must still record the signature., Invalid JSON is now treated as transient (mirrors raw is None): retry next run,…, The result-fallback recovers JSON shape but not the schema's enum constraint —…, The skip table is created by init_schema()'s executescript(schema.sql), which…, test_consolidation_settings_defaults(), test_consolidation_settings_env_override(), TestConsolidationSignatureSkip

### Community 118 - "_insert_injected_whisper_log"
Cohesion: 0.11
Nodes (25): _insert_injected_whisper_log(), Path, Once a judge signal exists, the same whisper row is not judged again., HIGH-2 refine (council-pr R2) + HIGH-3 (R3): the ENTIRE drain body — not just…, HIGH-3 (council-pr R3, Codex) USE-AFTER-CLOSE. The R2 test used an EMPTY watch…, Clear references in an assistant response create a signal and affinity row., Unreferenced whispers are observable but do not become negative affinity., The transcript watcher does not call the LLM unless the judge is enabled. (+17 more)

### Community 119 - "PromptClassifier"
Cohesion: 0.08
Nodes (22): PromptClassifier, Classify prompt intent using cosine similarity to archetype embeddings. Lazy-…, Classify *prompt* and return an intent with search-param overrides., ControlledEncoder, FakeEncoder, ndarray, Tests for the embedding-based prompt intent classifier., Test classification decisions with controlled cosine similarities. (+14 more)

### Community 120 - "mcp_adapter.py"
Cohesion: 0.16
Nodes (18): AsyncClient, _coerce_list(), _dispatch(), _format_maintenance_batches(), _format_timeout_error(), _handle_error(), _maintenance_key(), _poll_maintenance_until_ready() (+10 more)

### Community 121 - "compilerOptions"
Cohesion: 0.08
Nodes (23): compilerOptions, allowImportingTsExtensions, baseUrl, isolatedModules, jsx, lib, module, moduleResolution (+15 more)

### Community 122 - "background/__init__.py"
Cohesion: 0.12
Nodes (18): main(), CLI: python -m eval.maintenance.cli {mine|run|report} ... Local A/B eval gate…, _connect_ro(), mine_pairs(), Mine auto-link candidate pairs from a production store, read-only (#87 eval).…, agreement(), Agreement metrics for the single-vs-batched maintenance eval (#87 gate). Gate…, _load_pairs() (+10 more)

### Community 123 - "seed case"
Cohesion: 0.14
Nodes (14): clear_eval_db(), _parse_dt(), datetime, Seed the isolated whisper eval DB with memories from a corpus case., Parse an ISO/RFC3339 datetime string into a timezone-aware UTC datetime. Uses…, Remove all nodes from the eval DB and file store. When *preserve_self* is True,…, Return a datetime for *field* from corpus memory *mem*. Supported formats: -…, Clear eval DB and seed with memories from *case*. Memories are inserted with… (+6 more)

### Community 124 - "test_hybrid_search.py"
Cohesion: 0.10
Nodes (19): Tests for hybrid search scoring mechanics. These test the RRF fusion, threshold…, A node with valid_until in the past should be completely excluded from results., All identity tokens should be in the stop words list., If vector search fails, results should still come from FTS alone., Should never return more results than the limit., When tags filter is provided, get_tags_batch should be called once., Verify that FTS query uses bm25 column weights (title 10x, tags 5x). This is an…, FTS5 with porter stemmer matches morphological variants (live → lives). (+11 more)

### Community 125 - "test_eval_recall/test_report.py"
Cohesion: 0.19
Nodes (21): _arrow(), _bar(), format_report(), load_previous_run(), Path, Format recall eval reports and write results files., Write latest.json and append to history.jsonl., Return the last comparable history entry, or None if none exists. Runs at a… (+13 more)

### Community 126 - "run_decay"
Cohesion: 0.07
Nodes (39): Auto-demote working nodes whose FSRS retrievability drops below threshold., run_decay(), _get_tier(), _make_stale(), Tests for the decay manager background job., Demoted nodes should have an audit log entry recording the tier change., Set a node's last_accessed to `days` ago., Legacy pending decay proposals should be cleaned up on run. (+31 more)

### Community 127 - "compute whisper health"
Cohesion: 0.24
Nodes (18): compute_whisper_health(), datetime, Whisper effectiveness metrics derived from whisper_log + affinity. Read-only…, Return whisper coverage/precision over all_time and last_7d windows. ``now`` is…, _window(), _db(), _feedback(), _inject() (+10 more)

### Community 128 - "compilerOptions"
Cohesion: 0.09
Nodes (22): compilerOptions, allowImportingTsExtensions, forceConsistentCasingInFileNames, isolatedModules, jsx, lib, module, moduleDetection (+14 more)

### Community 129 - "desktop ui src App"
Cohesion: 0.20
Nodes (18): App(), Phase, TitleBar(), AgentInfo, InstallPanel(), currentWindow(), getInvoke(), graphUrl() (+10 more)

### Community 130 - "restore.py"
Cohesion: 0.10
Nodes (29): Result of restoring a memory backup., RestoreResult, key_file_exists(), CloudRestoreError, CloudRestoreResult, _committed_blobs(), _existing_store_id(), Any (+21 more)

### Community 131 - "detect_space_from_cwd"
Cohesion: 0.19
Nodes (14): detect_space_from_cwd(), Detect the project space from the current working directory. Tries git repo…, Tests for shared space detection., test_detect_fallback_to_cwd_basename(), test_detect_from_git_repo(), test_detect_from_git_subdirectory(), test_detect_handles_git_not_found(), test_detect_handles_git_timeout() (+6 more)

### Community 132 - "cloud/__init__.py"
Cohesion: 0.14
Nodes (18): Client-side cloud primitives: encryption, snapshot bundles, key lifecycle.…, canonical_memory_dir(), _entry_for(), _LockEntry, Path, Cross-process lock for operations that act on one local memory store., Return the stable local identity used for locking one memory directory., Return the lock path without consulting cloud enrollment or ``store_id``. (+10 more)

### Community 133 - "MemoryEngine facade"
Cohesion: 0.12
Nodes (21): Eval gating deliberately excluded from CI, ContextBuilder, FileStore, GraphIndex, IndexBuilder, Markdown is the source of truth, MemoryEngine facade, Write path (+13 more)

### Community 134 - "APScheduler background scheduler"
Cohesion: 0.13
Nodes (21): Connection (typed weighted edge), Core cap enforcement (50 nodes), CreateNodeRequest, EdgeType and activation factors, FSRS stability field, MemoryNode, Proposal (merge/conflict/decay), Tier (core / working / archival) (+13 more)

### Community 135 - "seed_case"
Cohesion: 0.21
Nodes (17): clear_eval_db(), datetime, Seed the isolated recall eval DB with memories from a corpus case., Return a created datetime for *mem*, or None for 'now'. Supports ``created``…, Clear eval DB and seed with memories from *case*. Memories are inserted with…, Remove all nodes from the eval DB and file store., seed_case(), _seed_created() (+9 more)

### Community 136 - "format_report"
Cohesion: 0.32
Nodes (8): _collect_failures(), _fmt(), format_report(), Format whisper eval results as a human-readable table., WhisperEvalResult, _make_eval_result(), _make_result(), TestFormatReport

### Community 137 - "_FakeEngine"
Cohesion: 0.12
Nodes (18): _FakeEngine, A single turn bigger than the budget can't make empty progress — commit it as…, Records the char length of every content payload sent to ingestion., A JSONL transcript whose closed content is well over flush_chars (60000)., Production wiring: a cap-limited flush calls on_defer_active so the retry Timer…, A flush that drains the whole closed delta (sub-cap) must not re-schedule —…, Primary production trigger: an ACTIVE (non-idle) session with MULTIPLE closed…, An active session whose total closed content stays below flush_chars never gets… (+10 more)

### Community 138 - "load_corpus"
Cohesion: 0.20
Nodes (16): CorpusError, load_corpus(), Exception, Path, Load and validate eval corpus files (JSONL format)., Raised on corpus file errors., Load a corpus JSONL file. Skips header lines. Returns list of cases. Raises…, Validate a single corpus case. Raises CorpusError on structural issues. (+8 more)

### Community 139 - "run_eval"
Cohesion: 0.18
Nodes (16): _aggregate(), _eval_case(), EvalResult, Recall eval runner: orchestrates per-case seeding, retrieval, and scoring., Compute aggregate metrics across all prompt results. Returns None for each…, Run the recall eval pipeline over *cases*. Returns EvalResult with per-case and…, Seed and evaluate a single corpus case., run_eval() (+8 more)

### Community 140 - "test_main_backfill_fallback.py"
Cohesion: 0.08
Nodes (32): _CancellableEngine, _monkeypatch_run_embedding_backfill(), fixture, _QuickEngine, Scheduler-independent embedding backfill fallback (#32, council C2/CH1/CH2).…, CH1: a second start while one is alive does not spawn a second thread., CH1: _stop_backfill_fallback stops a permanently-failing fallback., Completes immediately with no missing nodes. (+24 more)

### Community 141 - "Whisper pipeline (involuntary recall)"
Cohesion: 0.13
Nodes (20): Whisper path, Whisper candidate diagnostics and retention, Flat markdown whisper formatter, Prompt intent classification, Selective query enhancement for follow-ups, Session prompt ring buffer, Topic-shift skip, Whisper pipeline (involuntary recall) (+12 more)

### Community 142 - "configure_codex_mcp"
Cohesion: 0.15
Nodes (10): configure_codex_mcp(), Remove ormah entry from ~/.codex/config.toml., Remove a top-level TOML table block while preserving surrounding content., Write or update the Ormah MCP entry in ~/.codex/config.toml., Register Ormah MCP server in Codex config., _remove_codex_mcp_config(), _remove_toml_table_block(), _upsert_codex_mcp_config() (+2 more)

### Community 143 - "_create_pair"
Cohesion: 0.13
Nodes (19): _apply_edge(), Record a link decision: write to auto_link_checked and optionally create an…, _create_pair(), Helper: create two similar nodes without auto-linking, return their IDs., A concurrent writer created the same edge between collection and apply.…, The winner of the race already wrote its Connection to the file. We must not…, The winner committed the DB row but crashed before saving its markdown. The…, An INSERT OR IGNORE that inserted nothing is not a creation. Counting it as one… (+11 more)

### Community 144 - "_edges_between"
Cohesion: 0.14
Nodes (14): _edges_between(), LLM returns None -> no edge created (no heuristic fallback)., With llm_provider='none', LLM is never called and no edges are created., Return all edges between two nodes., Malformed LLM JSON → recorded as result='error' (no edge), so the node resolves., LLM classifies as supports -> edge created with type supports., LLM classifies as contradicts -> edge created with type contradicts., LLM classifies as none -> no edge created. (+6 more)

### Community 145 - "transfer.py"
Cohesion: 0.23
Nodes (10): download_file(), put_file(), Path, Data-plane transfers for service-issued presigned URLs., Stream an encrypted bundle to a presigned object URL., Stream a presigned object download to disk., _validated_put_headers(), mock (+2 more)

### Community 146 - "run_embedding_backfill"
Cohesion: 0.17
Nodes (13): Vector-store reconciliation job: backfill missing embeddings (#32)., Reconcile the vector store. Raises if the store is left incomplete. Unlike the…, run_embedding_backfill(), Tests for the embedding_backfill reconciliation job (#32)., An interrupted run (stop_event set) leaves missing>0, triggering RuntimeError., test_run_embedding_backfill_accepts_stop_event(), test_run_embedding_backfill_closes_gap(), test_run_embedding_backfill_ok_when_complete() (+5 more)

### Community 147 - "test_account_auth_routes.py"
Cohesion: 0.08
Nodes (32): load_or_create_local_admin_token(), Path, Request, Owner-only capability authentication for sensitive local API routes., Load this installation's local API capability, creating it mode 0600., Reject sensitive requests that did not originate on this machine., Authenticate a native local caller without exposing the cloud account token., require_local_admin() (+24 more)

### Community 148 - "test_stats.py"
Cohesion: 0.12
Nodes (19): _log_decision(), _log_whisper(), fixture, Tests for the canonical /stats endpoint., Candidates that were logged but not injected don't count as used., GET /agent/clients returns the agent list with detection and wired status., silence_rate + injection_rate must cover all prompts., Insert a synthetic whisper_log row mirroring context_builder's writer. (+11 more)

### Community 149 - "test_cloud_cli.py"
Cohesion: 0.14
Nodes (22): cloud_paths(), fixture, CLI tests for the `ormah cloud` group., `ormah cloud kit` is the recovery path when init/rotate is interrupted between…, Fresh-machine import must adopt the kit's store id, not mint a new one — the…, Point every cloud path at tmp and return the key path., A damaged store_id line must abort the whole import before any key material is…, _run() (+14 more)

### Community 150 - "visual"
Cohesion: 0.24
Nodes (13): applyAppearance(), buildGraph(), NOTE: store the domain node type under `nodeType`, NOT `type` — sigma, seedPosition(), computeSelfRoles(), displayNodeSize(), edgeColor(), nodeLabel() (+5 more)

### Community 151 - "_find_link_candidates"
Cohesion: 0.18
Nodes (8): _find_link_candidates(), Find node pairs that need link classification. Returns up to *limit* pairs as…, test_find_candidates_uses_window_without_advancing(), Tests for the run_maintenance two-call protocol., Create n nodes with similar content and return their IDs., _seed_similar_nodes(), TestApplyMaintenanceResults, TestFindLinkCandidates

### Community 152 - "test_routes_graph.py"
Cohesion: 0.22
Nodes (15): _insert_edge(), _insert_node(), fixture, Tests for /ui/graph active-first gating and space drill-down., test_default_all_spaces_includes_archival_only_space(), test_default_excludes_archival(), test_default_includes_user_node_even_if_archival(), test_default_no_space_false_when_all_nodes_have_space() (+7 more)

### Community 153 - "configure_claude_code_mcp"
Cohesion: 0.22
Nodes (6): configure_claude_code_mcp(), _merge_json_file(), Read a JSON file, deep-merge updates, and write back., Register ormah MCP server in Claude Code user config. Uses ``claude mcp add``…, TestConfigureClaudeCodeMcp, TestMergeJsonFile

### Community 154 - "conftest.py"
Cohesion: 0.16
Nodes (18): _clean_llm_cancel_epoch(), db(), engine(), file_store(), _is_real_ormah_path(), _is_relative_to(), isolate_fastembed_cache(), _isolate_settings_from_global_env() (+10 more)

### Community 155 - "test cli account"
Cohesion: 0.16
Nodes (12): account_paths(), FakeClient, fixture, parametrize, _run(), test_account_settings_are_loaded_from_environment(), test_login_keeps_credentials_when_entitlement_refresh_is_offline(), test_login_persists_credentials_without_rewriting_unrelated_lines() (+4 more)

### Community 156 - "TestSyntheticPromptEndpoint"
Cohesion: 0.13
Nodes (8): A machine-generated turn is skipped at the /agent/whisper boundary, BEFORE any…, matches everything and is falsy — the guard must test `is not None`. Truthiness…, Kill-switch coverage: it was dropped in 566fe3a when the guard moved., Rot detection is impossible without knowing WHICH pattern matched (#143)., Only silent_synthetic rows carry a pattern; everything else stays NULL., Dead sessions are evicted from _session_buffers on access (I12)., TestSessionBufferEviction, TestSyntheticPromptEndpoint

### Community 157 - "Ormah Desktop (Tauri v2 app)"
Cohesion: 0.13
Nodes (18): CI desktop job (Tauri + UI), uv sidecar download step, Bundled runtime (uv sidecar installs ormah from PyPI), Menubar tray presence (weekly whispers-used counter), Ormah Desktop (Tauri v2 app), desktop-product-bridge (trusted recovery handoff), Frozen ormah-server sidecar binaries directory, Desktop bootstrap UI HTML shell (+10 more)

### Community 158 - "TestReleaseVersionVerification"
Cohesion: 0.19
Nodes (7): CompletedProcess, Path, Tests for release packaging metadata and CLI fallbacks., TestBuildMetadata, TestEvalCliFallback, TestReleaseVersionVerification, TestReleaseWorkflow

### Community 159 - "scenario"
Cohesion: 0.13
Nodes (17): CONCEPT_EDGES, CONCEPT_NODES, CONTRADICTION_EDGES, CONTRADICTION_NODES, dedup(), dedupEdges(), EXPANDED_EDGES, EXPANDED_NODES (+9 more)

### Community 160 - "ORMAH  settings and .env load order"
Cohesion: 0.16
Nodes (18): App startup and shutdown sequence, Unwired node-file watcher, Whisper nudge and periodic whisper store, ormah whisper store, /ingest routes, FastAPI lifespan startup/shutdown, LLM feedback judge, Hippocampus markdown watcher (+10 more)

### Community 161 - "test_audit_log.py"
Cohesion: 0.20
Nodes (13): _create_node(), Tests for audit logging on delete, update, and mark_outdated., Helper to create a node, returns (id, slug)., delete_node should move the markdown file to deleted/ instead of removing it., Deleting a node writes a full snapshot to the audit log., Updating a node logs the old state and changed fields., Marking a node outdated logs the reason and old valid_until., list_audit_log filters by node_id and operation. (+5 more)

### Community 162 - "whisper/runner.py"
Cohesion: 0.27
Nodes (8): _aggregate(), _aggregate_by_category(), PromptResult, Whisper eval runner — seeds DB, calls full pipeline, collects metrics per…, Aggregate metrics across prompt results. Noise and non-noise are separated., Tests for eval/whisper/report.py., Tests for eval/whisper/runner.py., TestAggregate

### Community 163 - "compilerOptions"
Cohesion: 0.11
Nodes (17): compilerOptions, esModuleInterop, forceConsistentCasingInFileNames, lib, module, moduleResolution, noEmit, skipLibCheck (+9 more)

### Community 164 - "run_auto_cluster"
Cohesion: 0.15
Nodes (18): Automatic space/cluster assignment for unassigned nodes., Assign unassigned nodes to spaces based on their connections., run_auto_cluster(), _connect(), auto_cluster must not propagate the placeholder 'null' space (#22 council…, Startup migration re-locks legacy identity memories once (#22 council C)., The repair resets a swept identity cluster back to global + locked., Happy path still works: an unassigned node inherits a real neighbor space. (+10 more)

### Community 165 - "normalize_link_type"
Cohesion: 0.16
Nodes (16): _llm_classify_link(), Ask LLM to classify the relationship between two nodes. Returns a dict with…, normalize_conflict_type(), normalize_link_type(), Normalize LLM responses to canonical edge/conflict types., Map a raw LLM conflict type to a canonical value. Unknown values default to…, Map a raw LLM link type to a canonical value. Unknown values default to…, Tests for LLM response normalization functions. (+8 more)

### Community 166 - "test llm cancel"
Cohesion: 0.11
Nodes (15): Re-admit NEW calls after a RECOVERABLE cancel (the watcher's startup rollback).…, resume(), _clean_epoch(), fixture, Epoch semantics for LLM cancellation (ADR-0004 slice 2 redesign). These tests…, The watcher logs this count; it replaces the old "processes terminated" number., R4 regression. A resume() re-admits NEW calls; it must never un-cancel a call…, A final cancel must not outlive its lifespan: the llm_client adapter caches are… (+7 more)

### Community 167 - "extract_json"
Cohesion: 0.17
Nodes (17): extract_json(), Extract a JSON document from an LLM response. Thinking-capable models (e.g.…, Tests for fence-tolerant LLM JSON parsing shared across background jobs.…, A fenced-but-valid classification must yield the real relationship, not an…, Genuinely unparseable output (no JSON anywhere) yields an "error" result, never…, test_auto_linker_recovers_fenced_response_instead_of_poisoning(), test_auto_linker_treats_unparseable_output_as_poison(), test_extract_json_accepts_uppercase_fence_language() (+9 more)

### Community 168 - "load_corpus"
Cohesion: 0.20
Nodes (10): CorpusError, load_corpus(), Exception, Path, Load and validate whisper eval corpus files (JSONL format)., Raised on corpus file or validation errors., Load a JSONL corpus file. Skips blank lines. Validates each case., Tests for eval/whisper/corpus.py. (+2 more)

### Community 169 - "set_cloud_backup_enabled"
Cohesion: 0.21
Nodes (10): persist_settings_delta(), Structured persistence for cloud protection settings., Persist only keys changed by a caller, serialized with every other writer., Persist and apply cloud protection without dropping unrelated settings., set_cloud_backup_enabled(), env_path(), fixture, test_cloud_setting_does_not_change_runtime_when_persistence_fails() (+2 more)

### Community 170 - "_claude_code_wire"
Cohesion: 0.18
Nodes (10): _claude_code_wire(), install_claude_agents(), install_claude_commands(), Install ormah custom agent definitions into ~/.claude/agents/., Install ormah slash command definitions into ~/.claude/commands/., A stale enabled flag must not cost the user the whisper., Deliberate: the CLI hooks are global and serve every other project., Fail-open: an unparseable config must not silently disable the whisper. (+2 more)

### Community 171 - "test_protection_routes.py"
Cohesion: 0.08
Nodes (11): embedding_backfill must be a registered admin task in the sleep-cycle (#32)., C1/I1: a failed task yields status=degraded AND HTTP 503 (not 200)., Happy path stays a plain dict (HTTP 200) with status=completed., test_run_all_tasks_completed_returns_dict_when_all_ok(), test_run_all_tasks_degraded_returns_503_when_a_task_raises(), _poll(), parametrize, test_long_operations_return_202_and_poll_safe_results() (+3 more)

### Community 172 - "test_scoring_signals.py"
Cohesion: 0.11
Nodes (24): _make_node(), fixture, Tests for recency, access frequency, and tier scoring signals in hybrid search., A core node should outrank an archival node with the same base score., Boosts should not override a large relevance gap. RRF base scores are small…, Build a minimal node dict with scoring-relevant fields., Going from 0→5 accesses should give a larger boost than 15→20., With all boosts set to 0, ranking should match pure fusion. (+16 more)

### Community 173 - "configure_claude_hooks"
Cohesion: 0.18
Nodes (6): configure_claude_hooks(), Write Claude Code hook config to global settings using absolute paths., Non-list value on a claimed event (nested schema drift) must leave file…, A non-iterable 'hooks' value inside a matcher triggers the backstop: file is…, TestConfigureClaudeHooks, TestConfigureClaudeHooksMerge

### Community 174 - "test parser"
Cohesion: 0.14
Nodes (17): Tests for agent JSONL transcript normalization., A transcript whose RAW bytes dwarf its CLEANED conversation. Each turn carries…, The regression Amendment 3 exists to kill: tool-heavy turns must BATCH. Each…, A multi-turn slice's committed conversation stays within the budget — break…, The commit-site asymmetry: at the terminal-assistant site the budget check runs…, The progress guard: a lone turn bigger than the budget can't be shrunk, so it…, Tiny conversation, enormous raw span: the content budget is nowhere near full,…, A lone turn whose raw span exceeds the ceiling is committed anyway. Without… (+9 more)

### Community 175 - "forceLayout"
Cohesion: 0.14
Nodes (5): createForceLayout(), FA2Worker, ForceLayout, ForceLayoutOptions, STATIC_LAYOUT

### Community 176 - "permissions"
Cohesion: 0.12
Nodes (16): description, identifier, core:window:allow-close, core:window:allow-minimize, core:window:allow-start-dragging, core:window:allow-toggle-maximize, permissions, $schema (+8 more)

### Community 177 - "graph"
Cohesion: 0.12
Nodes (16): description, identifier, core:window:allow-close, core:window:allow-minimize, core:window:allow-start-dragging, core:window:allow-toggle-maximize, local, permissions (+8 more)

### Community 178 - "_write_env_file"
Cohesion: 0.18
Nodes (4): Write env dict to the global config file, preserving comments and ordering.…, _write_env_file(), TestEnvFile, TestWriteEnvPreservation

### Community 179 - "configure_codex_hooks"
Cohesion: 0.11
Nodes (10): configure_codex_hooks(), _install_hooks(), _merge_hooks(), Merge Ormah hook groups into an existing hooks dict, preserving co-tenants. For…, Read a JSON hooks config, merge Ormah hooks preserving co-tenants, write back.…, Write Codex hook config to ~/.codex/hooks.json and enable the feature flag., Non-list value on a claimed event (e.g. Stop) must leave file unchanged., TestConfigureCodexHooks (+2 more)

### Community 180 - "llm_cancel.py"
Cohesion: 0.14
Nodes (15): aborted(), begin_cancel(), begin_lifespan(), epoch_changed(), note_call_finished(), note_call_started(), Single authority for LLM call cancellation (ADR-0004 slice 2 redesign).…, Cancel the current epoch. Returns how many calls were in flight when it landed.… (+7 more)

### Community 181 - "MaintenanceManager"
Cohesion: 0.24
Nodes (7): MaintenanceManager, Any, Exception, Run maintenance phases in background threads with single-flight semantics., Start phase 1 if needed, or return the existing job state., Start phase 2 for the current prepared job., Return the current maintenance job state.

### Community 182 - "VectorStore"
Cohesion: 0.09
Nodes (27): embedding_text(), Canonical probe text for embeddings. Single source of truth: every vector in…, Build text for embedding. Truncates content to avoid topic averaging in long…, Any, ndarray, Vector storage and search using sqlite-vec., Return the stored embedding for *node_id*, re-encoding only if it is missing.…, Serialize a numpy float32 vector to bytes for sqlite-vec. (+19 more)

### Community 183 - "match synthetic pattern"
Cohesion: 0.20
Nodes (5): match_synthetic_pattern(), The source of the pattern that matched, or None when the prompt is human.…, Which pattern fired — the signal rot detection needs (#143)., The empty regex matches everything and returns "" — falsy but REAL. Callers…, TestMatchSyntheticPattern

### Community 184 - "_sanitize_fts_query"
Cohesion: 0.14
Nodes (14): Convert natural language query to FTS5-compatible queries. Returns a list of…, _sanitize_fts_query(), what is the user's name' should inject about_self into FTS tokens., grapes' has no identity token — should NOT inject about_self., does the user like grapes' should inject about_self., A query with only identity tokens (all stopped) should fall back to raw tokens…, my email' should inject about_self alongside 'email'., FTS query for 'user capitalism' should strip 'user' and produce just… (+6 more)

### Community 185 - "_claude_code_plugin_provides_hooks"
Cohesion: 0.16
Nodes (13): _claude_code_plugin_provides_hooks(), True when a user-scoped ormah plugin is enabled AND actually installed. Claude…, A stale enabled flag must never license deleting the working wiring., An interrupted update can leave the dir without its hooks manifest., Hooks alone don't prove the plugin also ships the MCP server it licenses…, Deliberate: the CLI hooks are global and serve every other project. Stripping…, The enabled key must be matched to the SAME registry key. A stale but healthy…, An interrupted update can leave hooks.json parseable but empty. (+5 more)

### Community 186 - "get_watermark"
Cohesion: 0.25
Nodes (12): get_watermark(), Shared seq-watermark helpers for incremental background jobs (#81). Generalizes…, Return the seq of the last fully-processed node for *key*, or 0., set_watermark(), Tests for the shared seq-watermark helpers (#81)., Mass reindex re-allocates seq; every incremental cursor must be cleared…, test_default_is_zero(), test_full_rebuild_resets_all_incremental_watermarks() (+4 more)

### Community 187 - "_node_dict"
Cohesion: 0.17
Nodes (13): _node_dict(), Convert a DB row to a plain node dict for candidate lists., mock_hybrid(), mock_hybrid_blended(), fixture, HybridSearch with blending enabled (default settings)., A result in FTS but not in vector results should score lower than one in both., Results below min_result_score should be excluded. With normalized RRF +… (+5 more)

### Community 188 - "UpdateNodeRequest"
Cohesion: 0.17
Nodes (25): UpdateNodeRequest, _archived_at(), A metadata edit (no tier change) must not move the clock., archival → working → archival must reset the clock, not keep the old one., test_demotion_to_archival_stamps_archived_at(), test_leaving_archival_clears_archived_at(), test_metadata_edit_while_archival_keeps_archived_at(), test_non_archival_update_does_not_stamp() (+17 more)

### Community 189 - "Desktop release build job (macOS + Linux matrix)"
Cohesion: 0.14
Nodes (15): Apple codesigning and dmg notarization, Desktop release build job (macOS + Linux matrix), macOS runner DNS resolver keepalive, Desktop release publish job, Rolling desktop-latest updater feed (latest.json), Desktop version guard (tag vs tauri.conf.json vs PyPI), RELEASE_ALLOWED_ACTOR and main-branch guard, Release build job (test + wheel) (+7 more)

### Community 190 - "HybridSearch pipeline"
Cohesion: 0.14
Nodes (15): about_self tag and FTS query injection, Identity system (self node + defines edges), SearchQuery, Candidate pool sizing (3x / 10x limit), HybridSearch pipeline, Long-document similarity penalty, Question-query weighting mode, Recall relevance floor (+7 more)

### Community 191 - "CloudProtectionService (reusable owner of backup now and res"
Cohesion: 0.18
Nodes (15): BackupService (local snapshot creation and restore path), bundle-manifest.json (per-file size + SHA-256 integrity manifest), Cloud backup (encrypted recovery point), cloud_status_payload() (single status derivation for CLI, REST, UI), CloudProtectionService (reusable owner of backup_now and restore verification), Hardened archive extraction allowlist (paths, links, collisions, byte caps), Derived index rebuild from Markdown (index.db excluded from bundles), Local backup + backup.json active Self pointer (+7 more)

### Community 192 - "Force-Directed Graph Canvas (full-bleed)"
Cohesion: 0.21
Nodes (15): Canvas-First Design (chrome minimized, no sidebar or legend), Node Color Encoding (tier / type signal), Dark Terminal Aesthetic (near-black canvas, monospace chrome), Force-Directed Graph Canvas (full-bleed), Ormah Graph Explorer UI (screenshot), Minimal Header Bar, Keyboard Shortcuts for Search (/ and Cmd+K), Lens-Shaped Dense Core Layout (+7 more)

### Community 193 - "cmd_eval_whisper_run"
Cohesion: 0.21
Nodes (4): cmd_eval_whisper_run(), Tests for eval whisper CLI wiring., TestEvalWhisperCLI, TestMakeEngine

### Community 194 - "main.py"
Cohesion: 0.05
Nodes (46): BaseHTTPMiddleware, FastAPI, AgentMiddleware, Request, Response, Request middleware for agent_id extraction and logging., get, Request (+38 more)

### Community 195 - ".generate"
Cohesion: 0.13
Nodes (14): _capture_pgid(), _cleanup_persisted_stub(), _kill_group_or_proc(), HIGH-2/HIGH-1 (council-pr, Codex): signal a child's WHOLE process group by its…, SIGTERM the child's process group (stored pgid); fall back to per-PID…, SIGKILL the child's process group (stored pgid); fall back to per-PID kill()., Best-effort: delete the child's own transcript stub. Even with --no-session-…, Snapshot the child's process-group id AT SPAWN, while the leader is guaranteed… (+6 more)

### Community 196 - "should rewind"
Cohesion: 0.19
Nodes (9): Gate the leading-orphan recovery on forward progress (ADR-0003, bug #149).…, should_rewind(), ADR-0003: rewind only on NO forward progress; an orphan-with-progress is…, The #149 byte pattern: end_turn boundary, then an assistant 'API Error' record…, A genuine legacy cursor parked mid-response: orphan AND no forward progress., No-progress alone (in-flight tail) must not rewind — only orphan+no-progress…, ADR-0003 large-orphan variant: a giant orphan fragment before the first user…, ADR-0003 accepted-loss pinning (council R1, Cursor+Codex): a GENUINE legacy… (+1 more)

### Community 197 - "Reconciling #126 (pair-verdict invalidation) with #208 (lock-order hoist) in IndexBuilder"
Cohesion: 0.17
Nodes (11): Design, Per entry point, Problem, Reconciling #126 (pair-verdict invalidation) with #208 (lock-order hoist) in IndexBuilder, Risk register, Scope, Signatures, Testing (+3 more)

### Community 198 - "TestGetMaintenanceBatches"
Cohesion: 0.18
Nodes (5): Issue #90 council R4: the finders fail INDEPENDENTLY (distinct queries, no…, A failing batch must block Phase 2's stamp, even though Phase 1 itself no…, No failures -> batch_errors == {}, no meta marker, and Phase 2 stamps…, A recovered system (finder works again) must stop being blocked — the next…, TestGetMaintenanceBatches

### Community 199 - "test graph"
Cohesion: 0.18
Nodes (12): graph(), _insert_node(), _insert_tag(), fixture, Tests for GraphIndex batch methods., GraphIndex backed by a real test database., Insert a minimal node row directly., Insert a tag for a node. (+4 more)

### Community 200 - "ormah setup wizard"
Cohesion: 0.14
Nodes (14): Model downloads on first run, One-click agent setup (ormah setup --json), NodeType (10 node types), Standing preference applicability channel, maintenance_due appended marker, Linear rescale of cross-encoder scores, FastEmbed model cache, Cross-encoder reranker (+6 more)

### Community 201 - "graph"
Cohesion: 0.27
Nodes (12): addEdge(), addNode(), EdgeDef, NodeDef, reconcile(), ScenarioFrame, EdgeType, GraphEdge (+4 more)

### Community 202 - "routes ingest"
Cohesion: 0.22
Nodes (13): ConversationLog, ingest_conversation(), ingest_file(), ingest_nudge(), NudgeRequest, BaseModel, post, Request (+5 more)

### Community 203 - "test_routes_admin_run_task.py"
Cohesion: 0.15
Nodes (11): app_and_client(), fixture, The manual task-trigger routes must not start a job that is already running,…, A manual trigger during the scheduled run used to start a second concurrent run…, The route returned {'status': 'completed'} unconditionally — a run that blew up…, run-all calls the runners directly too — same hole., The guard is only atomic against a SHARED tracker. It was created inside the…, test_lifespan_always_creates_a_job_tracker_even_if_the_scheduler_fails() (+3 more)

### Community 204 - "LocalAdapter"
Cohesion: 0.27
Nodes (4): LocalAdapter, ndarray, Wraps fastembed with lazy loading and caching., TestLocalAdapter

### Community 205 - "OllamaEmbeddingAdapter"
Cohesion: 0.25
Nodes (4): OllamaEmbeddingAdapter, ndarray, Produces embeddings via a local Ollama instance., TestOllamaAdapter

### Community 207 - "_run_fusion"
Cohesion: 0.17
Nodes (12): Run search with controlled FTS and vector outputs., A result with strong semantic match should outrank one with only keyword match., A result strong in both FTS and vector should outrank single-source results., Vector results below similarity_threshold should not contribute to scoring., Search should use get_nodes_batch instead of individual get_node calls., High-similarity vector result should score significantly higher than low-…, _run_fusion(), test_batch_node_fetch_used() (+4 more)

### Community 208 - "logging_setup.py"
Cohesion: 0.27
Nodes (8): LogRecord, Logging configuration — text or JSON format., Redact known API-key values from log text., Redact strings inside JSON log extras without changing non-secret types., Text formatter that redacts API-key values from the final rendered line., _redact_obj(), _redact_secrets(), _RedactingFormatter

### Community 210 - "NodeFileHandler"
Cohesion: 0.19
Nodes (9): NodeFileHandler, callable, FileSystemEventHandler, Observer, Path, File system watcher for memory node changes., Watches memory/nodes/ for file changes and triggers re-indexing., Start watching the nodes directory for changes. (+1 more)

### Community 211 - "test_run_stats.py"
Cohesion: 0.16
Nodes (13): Issue #90: maintenance runs return a stats dict., At the 1440-minute defaults the nominal offsets (5/15/30/45) are unscaled —…, Issue #90 council R3 finding 2: scaling each job by ITS OWN interval let jobs…, Issue #90 council R2 finding 1: a DB/encoder failure inside the finder must not…, Same as above for duplicate_merger's finder (also only reachable via…, _spy_add_job(), test_auto_linker_returns_stats(), test_conflict_detector_stats_shape() (+5 more)

### Community 212 - "LiteLLMEmbeddingAdapter"
Cohesion: 0.27
Nodes (4): LiteLLMEmbeddingAdapter, ndarray, Produces embeddings via litellm.embedding()., TestLiteLLMAdapter

### Community 213 - "constants"
Cohesion: 0.19
Nodes (10): Act1Void(), Props, TITLE_CHARS, ACTS_VH, COLORS, PHYSICS, STORY_VH, TOTAL_SCROLL_VH (+2 more)

### Community 214 - "GraphCanvas"
Cohesion: 0.32
Nodes (11): GraphCanvas(), Props, createGraphState(), setNodeOpacity(), endDrag(), hitTest(), nodeSize(), startDrag() (+3 more)

### Community 215 - "pi-plugin package"
Cohesion: 0.15
Nodes (12): author, bugs, url, contributors, description, homepage, license, main (+4 more)

### Community 216 - "test mcp adapter"
Cohesion: 0.23
Nodes (8): _FakeStdioServer, asyncio, test_call_tool_connect_error_recommends_supervised_start(), test_dispatch_polls_until_phase1_batches_are_ready(), test_dispatch_polls_until_phase2_apply_completes(), test_dispatch_submit_feedback_includes_whisper_log_id(), test_dispatch_uses_extended_timeout_for_maintenance(), test_run_mcp_stdio_generates_session_id_and_runs_server()

### Community 217 - "TestWhisperSignal"
Cohesion: 0.29
Nodes (4): No signal when claude_maintenance_enabled=False., No signal when maintenance was run within the interval., Signal appears when no maintenance has ever been run., TestWhisperSignal

### Community 218 - "Suppressing selection with a fact, not with the cursor (ADR-0004)"
Cohesion: 0.18
Nodes (10): Considered and rejected, Decision, Invariants, Residual risks, Selection suppression, Suppressing selection with a fact, not with the cursor (ADR-0004), Tests, The mechanism is a ratchet (+2 more)

### Community 219 - "strip temporal phrases"
Cohesion: 0.26
Nodes (4): Remove temporal phrases from *prompt*, returning the topical residue.…, strip_temporal_phrases(), Pure temporal queries should leave some residue (stop words)., TestStripTemporalPhrases

### Community 220 - "_remove_mcp_from_json"
Cohesion: 0.12
Nodes (13): _claude_code_unwire(), _claude_desktop_unwire(), Remove ormah agent definitions from ~/.claude/agents/., Remove ormah slash command definitions from ~/.claude/commands/., Remove ormah entry from mcpServers in a JSON config file., Remove the ormah instructions block from ~/.claude/CLAUDE.md., _remove_claude_agents(), _remove_claude_commands() (+5 more)

### Community 221 - "TestMarkOutdated"
Cohesion: 0.15
Nodes (6): feedback_engine(), fixture, Tests for the mark_outdated feedback tool., Engine with a node to give feedback on., An outdated memory should get a lower score in search., TestMarkOutdated

### Community 222 - "TestWhisperFailSilently"
Cohesion: 0.29
Nodes (3): Whisper should return empty string on failure, not dump everything., Prompts of 2 chars or less (e.g. 'y', 'ok') should return empty., TestWhisperFailSilently

### Community 223 - "test_miner.py"
Cohesion: 0.46
Nodes (12): _decision(), _log(), _make_db(), _node(), Path, Regression tests for the whisper eval miner. Build a temp SQLite DB with the…, _run_mine(), test_deterministic_truncation_keeps_injected_node() (+4 more)

### Community 224 - "Canonical Ormah guidance block (Claude memory file)"
Cohesion: 0.23
Nodes (12): Whisper eval case schema (memories, prompts, expectations), Six ormah_* Pi memory tools proxied to the HTTP API, Ormah-Pi extension (Pi coding agent memory layer), Pi transcript capture (compact/shutdown to POST /ingest/conversation), Pi whisper injection (POST /agent/whisper before each prompt), Ormah-Pi end-user setup playbook, Codex Ormah guidance block, maintenance_due whisper signal handling (+4 more)

### Community 225 - "run whisper log cleanup"
Cohesion: 0.24
Nodes (10): datetime, Bounded retention for high-volume whisper candidate diagnostics., Delete one bounded batch of stale, unreferenced rejected candidates. Injected…, run_whisper_log_cleanup(), _event(), Tests for normalized whisper payload retention., test_cleanup_deletes_only_stale_unreferenced_rejections(), test_cleanup_is_bounded_and_idempotent() (+2 more)

### Community 226 - "safe_error_message"
Cohesion: 0.21
Nodes (10): Guarded scheduler adapters for shared cloud protection operations., Run one scheduled backup, swallowing every exception at the scheduler boundary., Run weekly verification, swallowing every exception at the scheduler boundary., run_cloud_backup(), run_restore_verification(), Return a useful error without returning or logging credential-bearing material., safe_error_message(), test_persisted_error_keeps_nonsecret_path_for_cli_diagnostics() (+2 more)

### Community 227 - "TestWhisperDecisions"
Cohesion: 0.35
Nodes (3): Record a whisper call skipped because the prompt was machine-generated. Called…, Every whisper call writes exactly one whisper_decisions row (I10)., TestWhisperDecisions

### Community 228 - "SessionHandler"
Cohesion: 0.05
Nodes (30): _commit_state(), _is_subagent_transcript(), FileSystemEventHandler, Watches for .jsonl file create/modify events with debouncing., Debounce a file event, then ENQUEUE (never ingest) so the single drain owns…, Enqueue the file at its current EOF and wake the drain. The claim/dedup is the…, Start the always-on drain worker. Call after ``spool.recover()``., Signal that the spool has work. Never blocks — the request path calls this. (+22 more)

### Community 229 - "Global Constraints"
Cohesion: 0.33
Nodes (5): #126/#208 Reconciliation Implementation Plan, Global Constraints, Task 1: Merge and prove the deadlock test discriminates, Task 2: Apply the reconciliation, Task 3: Verify against the baseline and restore the worktree

### Community 230 - "install_claude_md"
Cohesion: 0.29
Nodes (3): install_claude_md(), Install ormah instructions into a Claude Code CLAUDE.md file., TestInstallClaudeMd

### Community 232 - "TestRecallFloorAndSpaceOrdering"
Cohesion: 0.30
Nodes (5): Deliberate recall: wider pool, space scores before the cut, relevance floor…, Cross-space noise penalized below the floor is dropped, not padded., A current-space match outside the old `limit` window survives the cut., A newer other-space node must NOT outrank an older current-space node., TestRecallFloorAndSpaceOrdering

### Community 233 - "._run_uninstall_with_mem_dir"
Cohesion: 0.27
Nodes (6): Verify that run_uninstall deletes the actual memory directory regardless of…, Helper: run uninstall with a faked settings.memory_dir., Old ormah used Path('memory') — server runs from ~, so data is at ~/memory., Custom absolute path outside XDG dirs is also cleaned up., memory_dir under ~/.local/share/ormah is already covered by XDG cleanup., TestUninstallMemoryDirResolution

### Community 234 - "whisper/cli.py"
Cohesion: 0.28
Nodes (8): _check_fail_below(), cmd_eval_whisper_import_labels(), cmd_eval_whisper_mine(), _make_engine(), CLI handler for `ormah eval whisper run`., Parse 'f1=0.65,suppression=0.90' and check thresholds. Returns 1 if any fails.…, import_labels(), Clear provisional flags on mined cases after human review. The review workflow…

### Community 235 - "TestStopOffsetCeiling"
Cohesion: 0.20
Nodes (7): ADR-0004 Task 3: ``stop_offset`` is an ABSOLUTE hard ceiling — no turn is…, Byte offset after the first ``upto`` records, matching ``_write_jsonl``'s…, The flagged leak: ``max_conversation_chars`` commits an oversized FIRST turn…, Everything closed at or before the ceiling is committed; the first turn that…, The non-nudge lane passes ``stop_offset=None`` and must parse exactly as before., The ceiling must also clamp the Codex ``task_complete`` closure site, not only…, TestStopOffsetCeiling

### Community 236 - "GraphView component (Cytoscape rendering + selection)"
Cohesion: 0.18
Nodes (11): AdminPanel (background task control via /admin/*), Edge opacity formula (max(0.2, weight or 0.5)), Graph appearance settings (localStorage ormah.graphAppearance.v1), GraphView component (Cytoscape rendering + selection), NodeDetail panel, Node sizing formula (24 + log2(access_count+1)*6), UI edge payload shape (source_id/target_id/edge_type/weight), /ui/graph data flow (load, filter client-side, node fetch, search) (+3 more)

### Community 237 - "test tool schemas"
Cohesion: 0.18
Nodes (5): get_openai_tools(), OpenAI function-calling schema adapter., Convert canonical tool schemas to OpenAI function-calling format., Canonical tool definitions shared across MCP and OpenAI adapters. TOOLS: The…, Focused tests for MCP-exposed tool schemas.

### Community 238 - "ormah/__init__.py"
Cohesion: 0.18
Nodes (9): _is_reserved_api_path(), get, Serve the SPA index.html for all non-API routes., serve_spa(), parametrize, Tests for the FastAPI app shell., test_local_admin_failure_disables_only_sensitive_routes(), test_spa_fallback_allows_frontend_routes() (+1 more)

### Community 239 - "relevance quarantine"
Cohesion: 0.24
Nodes (10): iter_dropped(), prompt_version(), Path, quarantine_path(), Durable, append-only quarantine ledger for memories dropped by the relevance…, Path to the quarantine JSONL file, beside the store DB (settings.db_path)., First 12 hex chars of sha256 of the ingest LLM rules prompt text., Append one dropped-candidate record to the quarantine ledger. *mode* is… (+2 more)

### Community 240 - "do install"
Cohesion: 0.42
Nodes (9): check(), do_check(), do_install(), install(), AppHandle, R, Result, String (+1 more)

### Community 241 - "validate_llm_runtime_config"
Cohesion: 0.22
Nodes (9): Server-startup guard — deliberately NOT a pydantic validator (council C2): the…, validate_llm_runtime_config(), provider=ollama with the (Anthropic) default llm_model must fail at SERVER…, council C3: ORMAH_LLM_MODEL= (empty string) overrides the default and must be…, The Anthropic default is only wrong for ollama — claude_cli keeps working., test_validate_llm_runtime_config_accepts_explicit_ollama_model(), test_validate_llm_runtime_config_keeps_claude_cli_default(), test_validate_llm_runtime_config_rejects_empty_ollama_model() (+1 more)

### Community 242 - "account.py"
Cohesion: 0.09
Nodes (44): _cached_entitlement(), Classify local entitlement state without network access during polling., AccountError, AccountStatus, _close_owned(), CodeRequestResult, get_account_status(), logout_account() (+36 more)

### Community 244 - "generate_server_wrapper"
Cohesion: 0.29
Nodes (3): generate_server_wrapper(), Generate daemon wrapper with explicit, scoped API-key inheritance., TestGenerateServerWrapper

### Community 245 - "Ormah Desktop App Icon (canonical 512px master)"
Cohesion: 0.36
Nodes (9): Ormah Desktop App Icon (canonical 512px master), Ormah Visual Brand Identity, Icon Color Palette (black / tan / teal), Dark Rounded-Square App Tile, Glowing Teal Node on the Ring, Letter 'O' Glyph Reading (Ormah wordmark initial), Memory-Graph Metaphor: a Single Lit Node on a Ring, Tan Open Ring / Orbit Motif (+1 more)

### Community 246 - "renderer"
Cohesion: 0.44
Nodes (8): drawNode(), edgeColor(), edgeGlowColor(), hexToRgba(), nodeSize(), render(), tierBorderColor(), tierColor()

### Community 247 - "Encoder factory (get encoder   get adapter)"
Cohesion: 0.28
Nodes (9): Local-first assumption, EmbeddingAdapter interface, Encoder factory (get_encoder / get_adapter), LiteLLMAdapter, LocalAdapter (FastEmbed / BGE), OllamaAdapter, Affinity boost computation, Affinity settings (+1 more)

### Community 248 - "Ormah system map"
Cohesion: 0.33
Nodes (9): Ormah system map, auto_cluster job, CLI adapter (sync HTTP client), MCP adapter (stdio to HTTP proxy), OpenAI adapter (schema exporter), Space detection resolution order, tool_schemas.py (TOOLS / ADMIN_TOOLS / ALL_TOOLS), /agent routes (+1 more)

### Community 249 - "age encryption envelope (client-side, private identity never"
Cohesion: 0.25
Nodes (9): age encryption envelope (client-side, private identity never leaves device), Ormah Cloud control plane (auth, entitlement, reservation, metadata), R2 data plane (ciphertext transfer), Immutable pending-to-committed promotion, Presigned URL (single-operation, single-key, short-lived storage permission), Recovery kit (store_id + retained age secret identities), Snapshot (committed encrypted cloud recovery point, server ULID), store_id (UUIDv4 identity of one local memory graph) (+1 more)

### Community 250 - "TestSpaceScoring"
Cohesion: 0.31
Nodes (5): Tests for score-based space prioritization in MemoryEngine., Same-space results score higher than otherwise-identical cross-project results., A high-relevance cross-project result still beats a weak current-project result., Global (space=None) results get the global boost factor., TestSpaceScoring

### Community 251 - "FakeProtectionService"
Cohesion: 0.22
Nodes (6): FakeProtectionService, _operation(), protection_app(), fixture, Path, ProtectionOperation

### Community 252 - "top2_recall"
Cohesion: 0.39
Nodes (3): Fraction of should_inject nodes in top-2 injected positions (shown in full)., top2_recall(), TestTop2Recall

### Community 253 - "TestWhisperIdentityGating"
Cohesion: 0.16
Nodes (9): _insert_node(), When topical results survive, identity should still be included., identity-only intent with no search results should stay silent (no graph dump)., Whisper should respect max_nodes., Total nodes in output should be <= max_nodes, even with identity nodes., Identity results should be suppressed when no topical results survive., High-scoring identity results should survive even without topical results., TestWhisperIdentityGating (+1 more)

### Community 254 - "hatch build"
Cohesion: 0.39
Nodes (6): BuildHookInterface, CustomBuildHook, _iter_ui_source_files(), Path, Hatch build hook — keeps the bundled UI current for packaged releases., _ui_needs_rebuild()

### Community 255 - "Ormah Project Banner Image"
Cohesion: 0.43
Nodes (8): Dark Warm Brand Palette (near-black, sand, teal accent), Memory-as-Constellation Metaphor, "ormah" Lowercase Wordmark, Ormah Project Banner Image, Dark Starfield Backdrop with Faint Orbital Halo, Teal Orb Glyph Beneath the Wordmark, Ormah Visual Identity, Wide Hero Aspect Ratio for README/Docs Header

### Community 256 - "Canonical ormah-maintenance agent (mcp  ormah  run maintenan"
Cohesion: 0.36
Nodes (8): Claude plugin ormah-maintenance agent, Two-call run_maintenance protocol (candidates then results), /ormah:maintenance command, Pi ormah-maintenance agent prompt (ormah_run_maintenance), Agent-backed maintenance (ORMAH_CLAUDE_MAINTENANCE_ENABLED, maintenance_due relay), Canonical ormah-maintenance agent (mcp__ormah__run_maintenance), Shipped ormah-pi-maintenance agent prompt, Shipped ormah-maintenance slash command

### Community 257 - "Ormah Claude Code plugin (manifest, hooks, MCP, commands)"
Cohesion: 0.54
Nodes (8): /ormah:setup command, /ormah:status command, /ormah:upgrade command, Ormah Claude Code plugin (manifest, hooks, MCP, commands), Plugin first-run flow (install, setup, claude-md install), ormah claude-md install (scope-matched guidance block), Claude plugin setup playbook, ormah setup --skip-client-setup (plugin-safe setup contract)

### Community 258 - "TestExtractionSchema"
Cohesion: 0.20
Nodes (5): confidence:0.0 is a legitimate, falsy value — must survive the `is None` check…, Regression: a memory 'content' that quotes a ```-fenced code block must not…, The fallback (`result`) extraction path is not --json-schema-constrained, so a…, content:null hits the same crash mode as the other three fields:…, TestExtractionSchema

### Community 259 - "test_hybrid_search_raw_cosine.py"
Cohesion: 0.33
Nodes (6): _make_hybrid(), _make_node(), Unit tests for the raw_cosine absolute-signal contract in HybridSearch. The…, A node found only via FTS (no vector hit) must carry no raw_cosine., A node with a genuine vector measurement keeps its raw_cosine., TestRawCosineContract

### Community 260 - ".search"
Cohesion: 0.29
Nodes (7): _is_question_query(), Any, Detect whether a query is a natural language question., Hybrid search with Reciprocal Rank Fusion. ``query_vec`` may be supplied by a…, parametrize, test_question_detection_negative(), test_question_detection_positive()

### Community 261 - "proposals.py"
Cohesion: 0.36
Nodes (7): Proposal, ProposalStatus, ProposalType, BaseModel, Enum, str, Proposal models for merge/conflict/decay actions.

### Community 262 - "_reciprocal_rank_fusion"
Cohesion: 0.25
Nodes (8): Fuse multiple ranked lists using weighted Reciprocal Rank Fusion. Each list…, _reciprocal_rank_fusion(), A node in both lists should score higher than one in only one list., Higher weight should give proportionally higher contribution., test_rrf_empty_lists(), test_rrf_overlap_accumulates(), test_rrf_single_list(), test_rrf_weights_scale_contribution()

### Community 263 - "test delete guarded"
Cohesion: 0.46
Nodes (6): _archival(), _exists(), A +feedback row inserted inside the guard's txn is visible to the guard's…, test_guard_false_aborts_deletion(), test_guard_observes_writes_in_same_transaction(), test_guard_true_deletes()

### Community 264 - "single instance listener"
Cohesion: 0.38
Nodes (6): integrate_appimage(), Option, Result, run(), single_instance_listener(), UnixListener

### Community 265 - "peerDependencies"
Cohesion: 0.29
Nodes (7): @earendil-works/pi-ai, @earendil-works/pi-coding-agent, peerDependencies, @earendil-works/pi-ai, @earendil-works/pi-coding-agent, typebox, typebox

### Community 266 - "install"
Cohesion: 0.52
Nodes (6): fail(), info(), ok(), install.sh script, step(), warn()

### Community 267 - "devDependencies"
Cohesion: 0.29
Nodes (7): devDependencies, tsx, @types/node, typescript, typescript, tsx, @types/node

### Community 268 - "peerDependenciesMeta"
Cohesion: 0.29
Nodes (7): optional, optional, peerDependenciesMeta, @earendil-works/pi-ai, @earendil-works/pi-coding-agent, typebox, optional

### Community 269 - "keywords"
Cohesion: 0.29
Nodes (7): keywords, agent, memory, ormah, pi, pi-extension, pi-package

### Community 270 - "run"
Cohesion: 0.43
Nodes (5): fail(), ok(), PATH, run.sh script, step()

### Community 271 - "test legacy backfill"
Cohesion: 0.57
Nodes (6): _legacy_archival(), _meta_done(), A node whose FILE lacks archived_at (remember(tier=archival) never stamps it)., test_backfill_skipped_when_disabled(), test_backfill_stamps_legacy_files_and_survives_rebuild(), test_backfill_write_failure_preserves_file_and_retries()

### Community 272 - "injection_precision"
Cohesion: 0.43
Nodes (3): injection_precision(), Fraction of injected nodes that were relevant. By default, relevance is defined…, TestInjectionPrecision

### Community 273 - "test_live_drain_recovers_a_job_stranded_in_running"
Cohesion: 0.50
Nodes (4): True once the spool holds no pending work and nothing is mid-flight in running/., council-pr R2 F1: a job orphaned in running/ (a requeue that itself failed on…, _spool_idle(), test_live_drain_recovers_a_job_stranded_in_running()

### Community 274 - "Any"
Cohesion: 0.33
Nodes (4): JobStatus, Any, Snapshot of a single job's health., Return a JSON-serialisable snapshot of all job statuses.

### Community 275 - "test recall concurrency"
Cohesion: 0.33
Nodes (6): Concurrency regression: recall must be safe when routes run in the threadpool.…, engine.graph.conn must resolve to the calling thread's own connection., Hammering recall_search from many threads must not raise (shared-conn race)., _remember(), test_concurrent_recall_does_not_raise(), test_graph_conn_is_per_thread()

### Community 276 - "InsightsPanel"
Cohesion: 0.33
Nodes (5): formatDate(), InsightsPanel(), Props, InsightNode, InsightsData

### Community 277 - "build"
Cohesion: 0.47
Nodes (5): App, build(), Result, server_status_label(), server_toggle_label()

### Community 278 - "verify release versions"
Cohesion: 0.73
Nodes (5): main(), Path, _read_plugin_version(), _read_project_version(), verify_release_versions()

### Community 279 - "files"
Cohesion: 0.33
Nodes (6): files, ormah-pi.ts, src, pi, extensions, agents

### Community 280 - "test_adapters.py"
Cohesion: 0.29
Nodes (4): Tests for embedding adapters and the provider registry., A populated store refuses a dim change; allow_drop authorizes it., TestDimensionMismatch, TestGetEncoderCaching

### Community 281 - "`frozen_until` Implementation Plan — Overview"
Cohesion: 0.33
Nodes (5): `frozen_until` Implementation Plan — Overview, Global Constraints, Line numbers, Setup (do this once, before Task 1), Tasks

### Community 282 - "test soft delete tombstone"
Cohesion: 0.73
Nodes (5): _make(), _store(), test_list_deleted_returns_id_and_deleted_at(), test_purge_removes_tombstone(), test_soft_delete_stamps_deleted_at()

### Community 283 - "test graph focus"
Cohesion: 0.47
Nodes (5): integration, Manual real-sigma smoke check: focusing a space frames it (no blank canvas).…, _space_bbox_in_viewport(), test_space_focus_frames_the_space(), _wait_settled()

### Community 284 - "has_false_positive"
Cohesion: 0.47
Nodes (3): has_false_positive(), True if any should_not_inject node appeared in injected output., TestFalsePositive

### Community 285 - "Whisper golden corpus (golden golden.jsonl, local-only)"
Cohesion: 0.50
Nodes (5): Case-design rules (labels precede runs, >=6 memories, named distractors), Whisper golden corpus (golden/golden.jsonl, local-only), Mined provisional cases (ormah eval whisper mine), Whisper F1 baselines table (2026-07-03), Maintenance decision rules (honest none, submit all evaluated pairs)

### Community 286 - "test graph drag"
Cohesion: 0.60
Nodes (4): first_node_screen_pos(), graph_pos(), main(), Drag test: dragging a node moves it; releasing re-heats FA2 so the graph keeps…

### Community 287 - "test graph layout"
Cohesion: 0.50
Nodes (4): main(), nearest_neighbor_dists(), Visual layout test: after FA2 settles, the layout is organic and NOT a grid.…, For each point, the distance to its closest other point.

### Community 288 - "NodeDetail"
Cohesion: 0.60
Nodes (4): NodeDetailPanel(), Props, timeAgo(), NodeDetail

### Community 289 - "repository"
Cohesion: 0.50
Nodes (4): repository, directory, type, url

### Community 291 - "CI test job"
Cohesion: 0.67
Nodes (3): CI runner disk-space monitor, CI lint job (ruff), CI test job

### Community 293 - "scripts"
Cohesion: 0.67
Nodes (3): scripts, test, typecheck

### Community 294 - "no default acceptance roots"
Cohesion: 0.67
Nodes (3): _no_default_acceptance_roots(), fixture, D8: the real ~/.claude/projects and ~/.codex/sessions exist on the dev machine,…

### Community 295 - "TestSessionBufferRoute"
Cohesion: 0.33
Nodes (4): Tests for the per-session prompt buffer in the whisper route., Buffer should accumulate prompts per session., Different session IDs should have independent buffers., TestSessionBufferRoute

### Community 296 - "run_mcp_stdio"
Cohesion: 0.40
Nodes (5): Server, create_mcp_server(), Run the MCP server over stdio transport., Create an MCP server that delegates to the HTTP API., run_mcp_stdio()

### Community 306 - "TestIngestConfidence"
Cohesion: 0.29
Nodes (4): Auto-ingested memories should default to confidence=0.7., If the LLM specifies confidence, it should be used., dry_run results should include the confidence value., TestIngestConfidence

### Community 340 - "test_migration_seq.py"
Cohesion: 0.33
Nodes (5): Tests for nodes.seq column migration and backfill., Regression: a pre-seq DB must migrate without 'no such column: seq'.…, Existing nodes get a monotonic seq ordered by created ASC., test_init_schema_migrates_legacy_db_without_seq(), test_seq_column_backfilled_by_created()

## Ambiguous Edges - Review These
- `Frozen ormah-server sidecar binaries directory` → `Bundled runtime (uv sidecar installs ormah from PyPI)`  [AMBIGUOUS]
  desktop/src-tauri/binaries/README.md · relation: conceptually_related_to
- `Node Color Encoding (tier / type signal)` → `Memory Graph Visualization (purpose of the view)`  [AMBIGUOUS]
  docs/graph.png · relation: conceptually_related_to
- `Whisper eval case schema (memories, prompts, expectations)` → `Pi transcript capture (compact/shutdown to POST /ingest/conversation)`  [AMBIGUOUS]
  integrations/pi-plugin/README.md · relation: conceptually_related_to
- `NodeDetail panel` → `Implicit feedback on whispered memories (submit_feedback + whisper_log_id)`  [AMBIGUOUS]
  docs/14 - Web UI.md · relation: shares_data_with
- `Ormah Desktop App Icon (canonical 512px master)` → `Memory-Graph Metaphor: a Single Lit Node on a Ring`  [AMBIGUOUS]
  desktop/src-tauri/icons/icon.png · relation: rationale_for
- `Teal Orb Glyph Beneath the Wordmark` → `Memory-as-Constellation Metaphor`  [AMBIGUOUS]
  docs/banner.png · relation: rationale_for

## Knowledge Gaps
- **366 isolated node(s):** `Global Constraints`, `Setup (do this once, before Task 1)`, `Tasks`, `Line numbers`, `Task 1: the suppression fact replaces the cursor advance` (+361 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Frozen ormah-server sidecar binaries directory` and `Bundled runtime (uv sidecar installs ormah from PyPI)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Node Color Encoding (tier / type signal)` and `Memory Graph Visualization (purpose of the view)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Whisper eval case schema (memories, prompts, expectations)` and `Pi transcript capture (compact/shutdown to POST /ingest/conversation)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `NodeDetail panel` and `Implicit feedback on whispered memories (submit_feedback + whisper_log_id)`?**
  _Edge tagged AMBIGUOUS (relation: shares_data_with) - confidence is low._
- **What is the exact relationship between `Ormah Desktop App Icon (canonical 512px master)` and `Memory-Graph Metaphor: a Single Lit Node on a Ring`?**
  _Edge tagged AMBIGUOUS (relation: rationale_for) - confidence is low._
- **What is the exact relationship between `Teal Orb Glyph Beneath the Wordmark` and `Memory-as-Constellation Metaphor`?**
  _Edge tagged AMBIGUOUS (relation: rationale_for) - confidence is low._
- **Why does `MemoryEngine` connect `MemoryEngine` to `patch`, `test_hippocampus.py`, `seed_case`, `memory_engine.py`, `_FakeEngine`, `run_eval`, `Settings`, `routes_agent.py`, `protection.py`, `test_stats.py`, `test_routes_graph.py`, `session_watcher.py`, `conftest.py`, `TestSyntheticPromptEndpoint`, `test_session_watcher_flush.py`, `llm_client.py`, `JobTracker`, `CreateNodeRequest`, `ContextBuilder`, `TestSessionBufferRoute`, `test_scoring_signals.py`, `test_whisper_context.py`, `MaintenanceManager`, `VectorStore`, `FileStore`, `IndexBuilder`, `UpdateNodeRequest`, `config.py`, `HybridSearch`, `PromptIntent`, `main.py`, `TestClient`, `ProtectionOperationCoordinator`, `test_ingest_extraction.py`, `test cleanup auto ingested`, `Database`, `test_routes_admin_run_task.py`, `test_init_vec_table_guard.py`, `get_fastembed_cache_dir`, `recall/cli.py`, `run_whisper_eval`, `TestWhisperFailSilently`, `TestSubmitFeedbackBasic`, `test relevance runner`, `run whisper log cleanup`, `TestWhisperDecisions`, `SessionHandler`, `start_scheduler`, `test_routes.py`, `TestRecallFloorAndSpaceOrdering`, `whisper/cli.py`, `conflict_detector.py`, `Connection`, `context_builder.py`, `_insert_injected_whisper_log`, `TestSpaceScoring`, `seed case`, `TestWhisperIdentityGating`, `run_decay`?**
  _High betweenness centrality (0.129) - this node is a cross-community bridge._