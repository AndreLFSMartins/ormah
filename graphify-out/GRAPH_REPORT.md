# Graph Report - ormah  (2026-08-16)

## Corpus Check
- 697 files · ~787,208 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 9715 nodes · 20469 edges · 559 communities (425 shown, 134 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2854 edges (avg confidence: 0.62)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `137f56e5`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ormah/cli.py
- test_session_watcher.py
- test_hippocampus.py
- CloudProtectionService
- product_bridge.rs
- IngestSpool
- Pi Plugin Client
- ProtectionOperationPhase
- rerank
- NodeType
- Tauri Sidecar Commands
- init_key
- test_config.py
- test_whisper_context.py
- load_state
- Ingest is async: the client nudges, the server owns the cursor and advances on job completion
- session_watcher.py
- test_synthetic_pattern_monitor.py
- GraphView.tsx
- Settings
- routes_agent.py
- TestClient
- test_claude_cli_adapter.py
- RecoveryKitError
- CloudState
- routes_account.py
- SessionHandler
- run_conflict_detection
- StoreLock
- test_session_watcher_flush.py
- config.py
- test_eval_whisper/test_metrics.py
- test_duplicate_merger.py
- JobTracker
- llm/__init__.py
- test_memory_engine.py
- Tauri Bundle Config
- test_whisper_out.py
- server_manager.py
- test_confirmed_use_contract.py
- open_bundle
- context_builder.py
- Database
- IndexBuilder
- CLI Adapter Tests
- _make_node_dict
- api.ts
- routes_admin.py
- configure_llm
- ContextBuilder
- ui/src/App.tsx
- billing.py
- test_ingest_extraction.py
- _insert_node
- test_main_lifespan_shutdown.py
- FileStore
- productBridge.ts
- dependencies
- setup.py
- backup.py
- Design — ingest Batch budgeted on conversation length (ADR-0001 Amendment 3)
- test_account_auth_routes.py
- test_ingest.py
- test_temporal_search.py
- run_uninstall
- get_or_create_store_id
- test_spreading_activation.py
- test_account_billing_routes.py
- CloudClient
- routes_protection.py
- ok
- test_eval_recall/test_metrics.py
- test cleanup auto ingested
- run_auto_linker
- cli_adapter.py
- CloudKeyError
- test_merge_undo.py
- test_seq_fingerprint.py
- hippocampus.py
- test feedback schema
- _make_titled_hybrid
- llm_cancel.py
- detect_space_from_cwd
- validate_case
- run_forgetting
- llm_client.py
- get_fastembed_cache_dir
- test pair batch
- src/types.ts
- Recomendações para o Ormah como projeto open source
- TestSafeBoundary
- CreateNodeRequest
- forgetting_manager.py
- restore.py
- run_setup_json
- TestSubmitFeedbackBasic
- test relevance runner
- _NeverEofProc
- test_db_concurrency.py
- run_whisper_eval
- EdgeType
- start_scheduler
- whisper/cli.py
- test_cloud_cli.py
- test_routes.py
- desktop ui package
- TierManager
- test_run_stats.py
- parse_transcript
- test_server_manager.py
- cmd_whisper_store
- GraphIndex
- HybridSearch
- setup_logging
- CloudCryptoError
- memory_engine.py
- extract_time_params
- test_routes_admin_run_task.py
- PromptIntent
- ControlledEncoder
- mcp_adapter.py
- compilerOptions
- background/__init__.py
- seed_case
- parser.py
- test_eval_recall/test_report.py
- CorpusError
- compute whisper health
- compilerOptions
- desktop/ui/src/App.tsx
- Lifecycle cluster — issue dossier
- extract_json
- find_rotted_patterns
- MemoryEngine facade
- APScheduler background scheduler
- test_hybrid_search.py
- _sanitize_fts_query
- configure_codex_mcp
- _is_ormah_hook
- local_auth.py
- test_main_backfill_fallback.py
- Whisper pipeline (involuntary recall)
- configure_codex_hooks
- auto_linker edge-write hardening — Overview
- compute_affinity_boost
- account.py
- recall/cli.py
- serialized_memory_job
- test_stats.py
- check_entitlement
- visual.ts
- _find_link_candidates
- routes_ui.py
- seed_case
- conftest.py
- test_cli_account.py
- TestSyntheticPromptEndpoint
- Ormah Desktop (Tauri v2 app)
- TestReleaseVersionVerification
- scenario
- ORMAH  settings and .env load order
- test_audit_log.py
- stored_or_encoded
- compilerOptions
- Review Relevance Is Not Confirmed Use — Implementation Plan
- normalize_conflict_type
- test_llm_cancel.py
- run_eval
- Review relevance is not confirmed use
- MemoryEngine
- _claude_code_wire
- test_protection_routes.py
- test_scoring_signals.py
- _linear_rescale
- test_parser.py
- forceLayout.ts
- permissions
- graph
- Investigação — o loop de rewind de cursor do #154 (2026-07-30)
- spool_proto.py
- claude_cli_adapter.py
- MaintenanceManager
- VectorStore
- match synthetic pattern
- 01-gate-the-claim.md
- patch
- test_setup.py
- test_consolidator.py
- test_migrations.py
- Desktop release build job (macOS + Linux matrix)
- HybridSearch pipeline
- CloudProtectionService (reusable owner of backup now and res
- Force-Directed Graph Canvas (full-bleed)
- cmd_eval_whisper_run
- 02-pin-legacy-fallback.md
- TestWhisperDebugMode
- TestWhisperTopicShift
- Reconciling #126 (pair-verdict invalidation) with #208 (lock-order hoist) in IndexBuilder
- TestGetMaintenanceBatches
- test graph
- ormah setup wizard
- graph
- routes ingest
- PromptClassifier
- safe_error_message
- .recall_search
- timedelta
- get_ormah_bin_path
- Whisper: detect rotted synthetic-prompt patterns and propose corrections — Design
- run_auto_cluster
- NodeFileHandler
- validate_llm_runtime_config
- Design — forgetting gate #6 must ignore non-value-bearing edges
- constants.ts
- GraphCanvas.tsx
- pi-plugin package
- test mcp adapter
- EmbeddingAdapter
- Suppressing selection with a fact, not with the cursor (ADR-0004)
- strip_temporal_phrases
- Design: ADR-0004 Fix A — stop dead-lettering `no_safe_boundary`
- install_pi_md
- format_report
- test_miner.py
- Canonical Ormah guidance block (Claude memory file)
- TestWhisperRerankerBlendIntegration
- should_rewind
- TestWhisperDecisions
- start_session_watcher
- Problemas de ingestão
- recall_search_structured Keyword-Only Tuning Parameters — Implementation Plan
- get_encoder
- TestRecallFloorAndSpaceOrdering
- Spinner
- TestStopOffsetCeiling
- test_index_embedding_retry.py
- GraphView component (Cytoscape rendering + selection)
- test tool schemas
- main.py
- relevance_quarantine.py
- updater.rs
- test_auto_linker.py
- set_cloud_backup_enabled
- Session-watcher live-loss safety net — Implementation Plan
- test_hybrid_search_raw_cosine.py
- Ormah Desktop App Icon (canonical 512px master)
- renderer
- Encoder factory (get encoder   get adapter)
- Ormah system map
- age encryption envelope (client-side, private identity never
- test_admin_embedding_backfill_task.py
- Design — session-watcher live-loss safety net
- Design: Claude-CLI memory extraction (replace local gemma)
- recall_search_structured: keyword-only tuning parameters
- hatch build
- Ormah Project Banner Image
- Canonical ormah-maintenance agent (mcp  ormah  run maintenan
- Ormah Claude Code plugin (manifest, hooks, MCP, commands)
- _node_dict
- _create_pair
- Avaliação profunda — ormah Beta (`local-main`) — 2026-07-13
- proposals.py
- Setup: skip the Claude Code wiring the ormah plugin already provides — Design
- test_delete_guarded.py
- single instance listener
- peerDependencies
- install
- devDependencies
- peerDependenciesMeta
- keywords
- run
- test legacy backfill
- Separate Surfaced Results from Confirmed Memory Use — Design
- llm_errors.py
- _remove_mcp_from_json
- test recall concurrency
- TestMarkOutdated
- build
- verify release versions
- files
- _remove_codex_hooks
- `frozen_until` Implementation Plan — Overview
- Investigação consolidada — ingestão (2026-07-30, tarde)
- test graph focus
- Ormah Memory Dashboard — Design
- _insert_node
- test graph drag
- test graph layout
- NodeDetail
- repository
- pair skip
- CI test job
- ormah
- scripts
- _no_default_acceptance_roots
- Whisper: skip synthetic (machine-generated) prompts — Design
- Embedding Delta Backfill + Continuous Reconciliation (#32) — Design
- test graph cluster
- build-sidecar
- ormah-mcp
- ormah-whisper-inject
- ormah-whisper-store
- text   init
- 01-suppression-fact.md
- Never advance the cursor without ingesting — design
- 02-reconcile-gate.md
- 03-enqueue-path-gate.md
- ormah
- 04-shrink-reset-clears.md
- 05-verify-and-merge.md
- test_migration_seq.py
- ingest-deferred-tracks.md
- Auditoria do ADR-0004 — 2026-08-09
- beta-keep (150 commits) — MUST survive the Task 6 merge (not in any PR, not upstream)
- test_soft_delete_tombstone.py
- Spec — isolate `test_setup.py` from the developer's machine
- LoggingHandler
- Draft comment for #209 — failure-mode analysis of the four-way duplicate policy
- get_watermark
- FakeProtectionService
- _edges_between
- LocalAdapter
- Runbook — running against the archived data directory (`ormah_old`)
- Graph Node Size by Degree — Design
- Graph view: WebGL live-force migration (sigma.js)
- Design: session-watcher catch-up off the bind path (#52)
- .stats
- _serialized_memory_operation
- Design — Graph active-first com drill-down de espaço (#22 slice 1)
- Design
- Design
- index_updater lock-order inversion — design
- ADR-0004 — repairing the two defects that break H1 in the ingest spool
- _claude_code_is_wired
- install_claude_md
- _run_fusion
- Investigação — pipeline de whisper — 2026-07-15
- Setup: stop clobbering pre-existing user config
- LLM Cancellation Redesign — Single Global Epoch
- OllamaEmbeddingAdapter
- .startup
- ._embed_node_rows
- Handoff — ADR-0004 slice 3 (`no_safe_boundary`): plano revisado 5×, nada implementado (2026-07-28)
- ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the queue
- Design: Session Watcher Cursor Safety
- Whisper-health metric — design
- ormah-backup-ux-check.sh
- TestSpaceScoring
- fit.test.ts
- UpdateBanner.tsx
- ADR-0004 Slice 2 — Bounded shutdown: cancel in-flight extractions
- Galaxy graph: tractable clustered layout at scale
- Graph Per-Space Cohesion (#22 slice B) — Design
- Verificação independente — problemas-de-ingestao.md
- Fork & contribution workflow (Ormah)
- Amendment 2026-08-11 — nothing shipped, the P1 gate never enforced, and move 2 loses its gate
- Proposal — Memory lifecycle: clock calibration, cold layer, and Deep Recall
- Beta ↔ Upstream Sync — Implementation Plan (overview)
- Delta-selection for dedup/conflict (#81) — Implementation Plan Overview
- .search
- Ingest batches are sized to a recall sweet spot, not the context window; delta ordered first
- Amendment 2026-08-09 — the 2026-07-28 force-close REMEDY is retracted; its DIAGNOSIS is confirmed and still open
- Amendment 2026-08-13 — Fix A ships: the `no_safe_boundary` dead-letter is retired, not just re-admitted
- ADR-0004 Async Ingest (Nudge + Server Cursor) — Implementation Plan
- ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the cursor
- Task 6: Rewrite GraphView as a sigma orchestrator
- Graph Per-Space Cohesion (#22 slice B) — Implementation Plan
- Plan delta — r-spade alignment (issue #73)
- Setup: skip the Claude Code wiring the ormah plugin already provides — Implementation Plan
- Synthetic-Pattern Rot Detection — Implementation Plan (overview)
- ADR-0004 Slice 3 — Extraction timeout: health-gated, shrink-first quarantine
- Cursor Rewind Loop Fix (#154) — Implementation Plan (Overview)
- Frozen-Prefix Cursor Loss — Overview
- Mapa do backlog upstream — local-main vs r-spade/ormah
- _reciprocal_rank_fusion
- Amendment 2026-08-13 — Fix B ships: suppression is a fact about the file, not a cursor advance
- Embedding Delta Backfill (#32) Implementation Plan — Overview
- Claude-CLI memory extraction — Implementation Plan (overview)
- ADR-0004 Spool H1 Repair — Overview
- _remove_fastembed_cache
- TestWhisperSignal
- Amendment 2026-08-11 — H1's "retry forever" has a hard stop at attempt 1025, and a deleted transcript never reaches the dead-letter
- Amendment 2026-07-28 — slice 3: the frozen tail is force-closed automatically, behind an anti-rewind checkpoint
- Draft — reply to r-spade on PR #31 — SUPERSEDED 2026-07-14
- Problema 1 — o julgamento de relevância é um prompt, não um gate
- Graph view WebGL live-force migration — Implementation Plan (overview)
- Graph active-first com drill-down de espaço — Implementation Plan (#22 slice 1)
- Task 6 — Fixes do council v2 (C1/C2/C3) + cobertura
- SPIKE-FINDINGS — Task 01 (GATE)
- ADR-0003 — Orphan Progress Guard: Implementation Plan (Overview)
- index_updater Lock-Order Inversion — Implementation Plan
- Separate Surfaced Results from Confirmed Memory Use — Implementation Plan
- Setup Test Env Isolation — Overview
- FakeEncoder
- routes_stats.py
- ._write_audit_log
- .test_ce_reorders_results
- TestSessionBufferRoute
- Problema 3 — o churn de `seq` (refutado como causa do backlog)
- Task 3 — Pure helpers: `buildSpaceLegend` + `scopeLabel`
- live_patterns
- .test_exactly_at_threshold_passes
- Recovery drops an orphan fragment rather than re-ingesting the whole transcript
- ⛔ SUPERSEDED — this plan was split into three slices (2026-07-21)
- Task 4 — Wiring: `App.tsx` (estado + fetch) e `GraphView.tsx` (legenda drill + banner)
- Task 2: Add `_claude_code_plugin_provides_hooks()`
- Task 2: Always-on Ingest worker — drains the spool; Observer becomes optional
- test_expired_tombstone_is_purged_and_audited
- Task 2: `POST /ingest/nudge` — 202, feeds the worker
- Task 03: `_missing_embeddable_count()` + `backfill_embeddings()`
- Task 2 — Rebase the 5 small PRs (#57 → #60 → #68 → #38 → #31)
- Task 4: The `_claude_code_wire` guard — skip and strip
- Task 1: The ingest spool — a durable queue made of files
- Task 4: Land it in the Beta
- Task 01 — The backoff saturates instead of overflowing
- Task 02 — A deleted transcript is dead-lettered, not retried forever
- Task 03 — Prove no other ENOENT sink survives, then verify everything
- Task 2: Qualified positive feedback records confirmed use
- 01 — PR #229 closed as superseded, confirmed
- 02 — @r-spade confirms the Discord transcriptions (+ #217 closure)
- 03 — PR #133 lands, then PR #95 rebases
- 04 — reference regime for store measurements
- 05 — validating the `auto_llm_judge` confirmed-use path with the watcher off
- 07 — #209 approach decided and the owed comment posted
- 08 — ownership of #218 fixes 1–2
- 09 — ownership of #219 (audit_log retention + VACUUM)
- 10 — disposition of #151 (ingest relevance gate)
- 11 — disposition of #192 (consolidator truncation)
- 12 — disposition of #193 (edge `reason` lost in markdown round-trips)
- 13 — disposition of #194 (conflict candidates missing creation dates)
- 14 — flip criteria for bounded forgetting (#28 / PR #31)
- 15 — macro planning for #224 (system-level conflict owner)
- test_full_rebuild_resets_watermark
- flows.md
- 2026-07-21-adr-0004-async-ingest-nudge-SUPERSEDED/01-timeout-signal.md
- 2026-07-21-adr-0004-async-ingest-nudge-SUPERSEDED/02-timeout-classification.md
- 03-always-on-worker.md
- 04-nudge-endpoint.md
- 05-hook-pure-nudge.md
- 06-verification-and-integration.md
- 07-shutdown-cancellation.md
- 01-always-on-worker.md
- 03-hook-pure-nudge.md
- 04-verification.md
- 2026-06-16-embedding-delta-backfill/01-config.md
- 02-embed-node-rows.md
- 04-index-embedding-retry.md
- 05-startup-remove-block.md
- 06-background-job.md
- 07-scheduler-register.md
- 08-admin-run-all.md
- 09-scheduler-independent-fallback.md
- 10-observability-and-e2e.md
- 01-tooling-and-deps.md
- 02-visual-helpers.md
- 03-graph-model.md
- 04-sigma-reducers.md
- 05-force-layout.md
- 07-playwright-visual.md
- 08-cleanup-and-verify.md
- 01-backend-gating.md
- 02-frontend-types-api.md
- 05-verify.md
- 01-cross-space-mixing.md
- 02-cluster-layout.md
- 03-cluster-toggle.md
- 04-graphview-wiring.md
- 2026-06-30-graph-space-cohesion/05-verification.md
- 01-spike-auth-envelope.md
- 02-claude-cli-adapter.md
- 03-provider-wiring-config.md
- 04-recursion-guard-exclusion.md
- 05-cursor-unification.md
- 06-enablement-e2e.md
- 01-preflight-inventory.md
- 03-rebase-pr79-with-hardening.md
- 04-pr87-open.md
- 05-assembly-branch.md
- 06-merge-into-beta.md
- 07-runtime-verify-close.md
- 01-watermark-module.md
- 02-conflict-finder-delta.md
- 03-conflict-run-advance.md
- 04-dedup-finder-delta.md
- 05-dedup-run-rewrite.md
- 00-atomic-mcp-write.md
- 01-is-wired-dead-branch.md
- 03-is-wired-plugin-aware.md
- 01-match-synthetic-pattern.md
- 02-matched-pattern-column.md
- 03-detection-logic.md
- 04-job-and-registration.md
- 01-should-rewind-predicate.md
- 02-session-watcher-gate.md
- 03-whisper-hook-gate.md
- 04-integration-pr-beta.md
- 03-nudge-endpoint.md
- 04-hook-pure-nudge.md
- 2026-07-21-adr-0004-slice1-nudge-core/05-verification.md
- 01-cancel-seam.md
- 02-shutdown-cancellation.md
- 2026-07-21-adr-0004-slice2-bounded-shutdown/03-verification.md
- 2026-07-21-adr-0004-slice3-timeout-quarantine/01-timeout-signal.md
- 2026-07-21-adr-0004-slice3-timeout-quarantine/02-timeout-classification.md
- 2026-07-21-adr-0004-slice3-timeout-quarantine/03-verification.md
- task-1-drain-progress-gate.md
- task-2-monotonic-commit-backstop.md
- task-3-config-validator.md
- 01-cost-guard.md
- 02-the-fix.md
- 03-prove-recovery.md
- 01-red-test.md
- 02-fix.md
- 03-verify.md
- 04-ship.md
- 01-stop-surfacing-writes.md
- 01-reproduce-red.md
- 02-settings-singleton.md
- 03-find-binary-seam.md
- 04-verify-branch.md
- ._extract_time_params
- backup_dir
- ormah-desktop
- _isolate_cache
- test_low_confidence_penalized_more
- test_length_penalty_disabled_at_zero
- test_keyword_query_still_uses_title_boost

## God Nodes (most connected - your core abstractions)
1. `Settings` - 203 edges
2. `MemoryEngine` - 150 edges
3. `CreateNodeRequest` - 142 edges
4. `ContextBuilder` - 140 edges
5. `NodeType` - 136 edges
6. `CloudProtectionService` - 119 edges
7. `parse_transcript()` - 96 edges
8. `load_state()` - 93 edges
9. `_mark_idle()` - 93 edges
10. `_make_node_dict()` - 85 edges

## Surprising Connections (you probably didn't know these)
- `Pi ormah-maintenance agent prompt (ormah_run_maintenance)` --semantically_similar_to--> `Shipped ormah-pi-maintenance agent prompt`  [INFERRED] [semantically similar]
  integrations/pi-plugin/agents/ormah-maintenance.md → src/ormah/agents/ormah-pi-maintenance.md
- `test_inverted_cluster_bounds_returns_empty_and_warns()` --calls--> `_find_consolidation_clusters()`  [INFERRED]
  tests/test_background/test_consolidator.py → src/ormah/background/consolidator.py
- `test_consolidation_settings_defaults()` --uses--> `Settings`  [INFERRED]
  tests/test_background/test_consolidator.py → src/ormah/config.py
- `test_consolidation_settings_env_override()` --uses--> `Settings`  [INFERRED]
  tests/test_background/test_consolidator.py → src/ormah/config.py
- `test_extraction_uses_ingest_adapter_not_maintenance()` --uses--> `Settings`  [INFERRED]
  tests/test_background/test_ingest_provider.py → src/ormah/config.py

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

## Communities (559 total, 134 thin omitted)

### Community 0 - "ormah/cli.py"
Cohesion: 0.10
Nodes (49): cmd_eval_recall_import_labels(), main(), Entry point for MCP stdio server., _backup_service(), _backup_to_dict(), _cloud_client(), _cmd_account_login(), _cmd_account_logout() (+41 more)

### Community 1 - "test_session_watcher.py"
Cohesion: 0.03
Nodes (184): _ingest_session(), IngestResult, Why an ingest attempt did/didn't commit, so reconcile parks only files that…, Ingest a single JSONL session transcript if changed. ``boundary`` is the…, _append_assistant(), _append_codex_turn(), _append_pair(), _append_user() (+176 more)

### Community 2 - "test_hippocampus.py"
Cohesion: 0.07
Nodes (37): _load_state(), Observer, Scan a directory for new/changed .md files. Returns count of files ingested., Stop and join all hippocampus observers., One-shot scan of all watch dirs (for admin trigger / manual catch-up)., Load persisted state for a watch directory., run_hippocampus_scan(), _scan_directory() (+29 more)

### Community 3 - "CloudProtectionService"
Cohesion: 0.08
Nodes (48): ProtectionState, key_file_exists(), _cleared_upload_journal(), _cloud_error_code(), CloudProtectionService, _EnablePrerequisiteError, _existing_store_id(), _finalize_is_definitively_expired() (+40 more)

### Community 4 - "product_bridge.rs"
Cohesion: 0.08
Nodes (76): account_status(), AccountStatus, backup_now(), billing_offer(), BillingOffer, bind_protection_intent(), cancel_protection_intent(), cancel_restore() (+68 more)

### Community 5 - "IngestSpool"
Cohesion: 0.04
Nodes (63): IngestSpool, Path, Durable ingest queue built from directory entries (ADR-0004 Amendment…, Enqueue a job. The boundary lives in the filename: a second, slower nudge for…, Claim the oldest due pending job. The rename IS the mutual exclusion. ⚠️ This…, Mark a job done. Idempotent: completing an already-completed job must not…, Return a claimed job to pending/, or dead-letter it, keyed on failure CLASS --…, Move a job to failed/ WITH its original bytes -- never unlink without first… (+55 more)

### Community 6 - "Pi Plugin Client"
Cohesion: 0.05
Nodes (41): ormahPi(), IngestBody, MaintenanceResults, OrmahClient, OrmahHttpError, RecallBody, RememberBody, WhisperResponse (+33 more)

### Community 7 - "ProtectionOperationPhase"
Cohesion: 0.09
Nodes (74): ProtectionOperationPhase, ProtectionReasonCode, StrEnum, Durable client phases around the only ambiguous upload boundary., Stable machine-readable causes shared by CLI, REST, and desktop clients., UploadJournalPhase, cloud_state_dir(), FakeCloudClient (+66 more)

### Community 8 - "rerank"
Cohesion: 0.08
Nodes (25): Rerank search results using a cross-encoder with linear-rescale blended…, rerank(), _candidate(), Unit tests for the cross-encoder reranker with linear-rescale blended scoring.…, Verify min_score threshold applies to blended score., Build a minimal search result dict., Verify the output preserves debugging information., Verify the query/doc pairs built for the cross-encoder. (+17 more)

### Community 9 - "NodeType"
Cohesion: 0.04
Nodes (93): Tier promotion/demotion and core cap enforcement., The ingest extraction prompt contract: rules, response schema, rendered…, MemoryNode, NodeType, Enum, Core domain models for memory nodes., Advance `updated`. Call before saving any content mutation; never for read-side…, BaseModel (+85 more)

### Community 10 - "Tauri Sidecar Commands"
Cohesion: 0.06
Nodes (58): Command, base_url(), detect_agents(), fetch_stats(), graph_url(), is_onboarded(), mark_onboarded(), marker_path() (+50 more)

### Community 11 - "init_key"
Cohesion: 0.08
Nodes (51): _cmd_cloud_init(), _atomic_write_0600(), current_recipient(), extract_store_id(), import_key(), init_key(), load_identities(), load_identity_strings() (+43 more)

### Community 12 - "test_config.py"
Cohesion: 0.05
Nodes (70): parametrize, Tests for config validation., Create settings with overrides, using a temp dir for memory_dir., council C2: constructing Settings must NEVER raise for this pair — `ormah…, _settings(), test_activation_decay_one_ok(), test_activation_decay_zero(), test_affinity_defaults() (+62 more)

### Community 13 - "test_whisper_context.py"
Cohesion: 0.06
Nodes (29): _make_settings_mock(), Tests for whisper context (involuntary recall injection)., Create a MagicMock settings object with affinity-related float attributes., Affinity boost rescues candidates that would otherwise be gated out., A candidate below the injection gate that receives a strong affinity boost…, Affinity boost is only applied when reranker_enabled=True., If affinity boost raises, the pipeline should continue with unmodified scores., A strong negative affinity boost should push a marginal candidate below the… (+21 more)

### Community 14 - "load_state"
Cohesion: 0.13
Nodes (56): load_state(), ProtectionIntentStatus, ProtectionState, User-facing states for the paid backup protection journey., Load one store's state, distinguishing absence from unsafe existing data., Durable phases for an explicit Protect action., Update selected fields while preserving the rest of one store's state., update_state() (+48 more)

### Community 15 - "Ingest is async: the client nudges, the server owns the cursor and advances on job completion"
Cohesion: 0.18
Nodes (11): Amendment 2026-07-22 — the durable queue is a directory spool, not the Cursor alone (and not a job table), Amendment 2026-08-10 — the cause is found: the frozen-prefix jump is a WINDOWED-parse artefact, Amendment 2026-08-12 — the windowed-parse defect reproduces post-wipe; neither fix from 08-09/08-10 has shipped, Consequences, Considered options, Field observation 2026-07-27 — the `no_safe_boundary` dead-letter has 533 transcripts and no drain, Ingest is async: the client nudges, the server owns the cursor and advances on job completion, Narrowed: `_mark_frozen_prefix_consumed` is not the only writer of the `{end_offset}` shape (+3 more)

### Community 16 - "session_watcher.py"
Cohesion: 0.05
Nodes (68): Re-admit new LLM calls after a RECOVERABLE cancel (the watcher's startup…, resume_llm_adapters(), _assistant_response_after_prompt(), _confidence(), _drain_handlers(), _feedback_llm_judge_enabled(), _insert_affinity(), _insert_usage_signal() (+60 more)

### Community 17 - "test_synthetic_pattern_monitor.py"
Cohesion: 0.09
Nodes (34): _decision(), Rot detection for the synthetic-prompt pattern list (#143)., council C1. With the filter off nothing writes silent_synthetic, so every…, council I4. One match months ago is not evidence of a live workflow., Rewritten from the old global vacation guard, which the opportunity guard…, The old global guard was satisfied by ONE prompt after a month away and…, The mirror case: the marker really did stop, and there was plenty of traffic in…, History for a pattern the user already deleted is not actionable. (+26 more)

### Community 18 - "GraphView.tsx"
Cohesion: 0.07
Nodes (37): BANNER_BTN_STYLE, BANNER_STYLE, clampZoomSliderValue(), DRILL_BTN_STYLE, GraphView, LEGEND_PANEL_STYLE, LEGEND_ROW_STYLE, LEGEND_SECTION_TITLE_STYLE (+29 more)

### Community 19 - "Settings"
Cohesion: 0.06
Nodes (7): BaseSettings, field_validator, True when an LLM provider is configured (not ``"none"``)., Settings, Tests for embedding adapters and the provider registry., TestGetAdapter, TestGetEncoderCaching

### Community 20 - "routes_agent.py"
Cohesion: 0.07
Nodes (59): delete, HTTPException, connect(), delete_node(), FeedbackRequest, get_clients(), get_insights(), get_maintenance_status() (+51 more)

### Community 21 - "TestClient"
Cohesion: 0.09
Nodes (35): FastAPI, TestClient, protection_app(), fixture, Path, app_and_client(), fixture, client() (+27 more)

### Community 22 - "test_claude_cli_adapter.py"
Cohesion: 0.07
Nodes (58): ClaudeCliAdapter, LlmCancelledError, The call was cancelled by the host (shutdown/stop), not by the provider. Says…, _fake_popen(), _pid_alive(), integration, skipif, Belt-and-suspenders against the real binary: an operator SessionStart hook must… (+50 more)

### Community 23 - "RecoveryKitError"
Cohesion: 0.07
Nodes (31): Path, RuntimeError, Validate the canonical kit and confirm a reopened native saved copy., Validate the fixed canonical kit without changing readiness., Repair a stale canonical kit before a native save operation. Returns ``True``…, Record a saved-copy proof only when its bytes equal the current valid kit., Clear readiness before installing a recovery-first key rotation. The ordering…, Raised when recovery material cannot be proven current and complete. (+23 more)

### Community 24 - "CloudState"
Cohesion: 0.07
Nodes (65): _mark_checkout_pending(), Atomically revalidate and reserve this durable intent for Checkout., _as_utc(), cloud_status_payload(), CloudState, CloudStateLoadError, _ensure_writable_schema(), _existing_store_id() (+57 more)

### Community 25 - "routes_account.py"
Cohesion: 0.09
Nodes (43): account_checkout(), _account_http_error(), account_logout(), account_offer(), account_portal(), account_request_code(), account_status(), account_verify_code() (+35 more)

### Community 26 - "SessionHandler"
Cohesion: 0.03
Nodes (69): _commit_state(), _default_acceptance_roots(), _file_hash(), _frozen_unchanged(), _is_nested_or_equal(), _is_subagent_transcript(), _load_state(), ParkOutcome (+61 more)

### Community 27 - "run_conflict_detection"
Cohesion: 0.07
Nodes (57): _conflict_scope_value(), _find_conflict_candidates(), Find node pairs that might contradict each other. ``delta=False`` (default —…, Find potentially contradicting nodes and create edges. Seeds are delta-selected…, run_conflict_detection(), _conflict_response(), _create_pair(), _make_belief() (+49 more)

### Community 28 - "StoreLock"
Cohesion: 0.11
Nodes (23): Client-side cloud primitives: encryption, snapshot bundles, key lifecycle.…, canonical_memory_dir(), _entry_for(), _LockEntry, Path, Cross-process lock for operations that act on one local memory store., Raised when another process keeps a memory store busy past the timeout., Return the stable local identity used for locking one memory directory. (+15 more)

### Community 29 - "test_session_watcher_flush.py"
Cohesion: 0.04
Nodes (60): _FakeConn, _FakeEngine, fixture, Presence detection must not fire on a commented-out line or on a longer key…, Review M-9: the repo owner's ordered fix (warn instead of silently `continue`…, Regression for review F1: with no ~/.config/ormah/.env and no ./.env,…, The F1 fix must not over-correct into swallowing a REAL read failure…, Council R1 (Cursor): a floor of `>= flush_chars` compares bytes to chars and… (+52 more)

### Community 30 - "config.py"
Cohesion: 0.10
Nodes (19): model_validator, _deprecated_key_present(), Path, Application configuration via environment variables and .env file., True when the deprecated key is set in ANY configured settings source.…, _ingest_adapter_baseline_timeout(), _prompt_exceeds_provider_capacity(), The timeout the ACTIVE ingest adapter would use on its own. Adapters treat… (+11 more)

### Community 31 - "test_eval_whisper/test_metrics.py"
Cohesion: 0.07
Nodes (21): compute_prompt_metrics(), f1_score(), has_false_positive(), injection_precision(), injection_recall(), Metrics for whisper eval: injection recall, precision, f1, top2_recall,…, Fraction of injected nodes that were relevant. By default, relevance is defined…, Fraction of should_inject nodes in top-2 injected positions (shown in full). (+13 more)

### Community 32 - "test_duplicate_merger.py"
Cohesion: 0.08
Nodes (53): Find near-duplicate nodes and create merge proposals. Uses a multi-signal…, run_duplicate_detection(), _create_pair(), _duplicate_response(), _make_fact(), Tests for LLM-based duplicate consolidation in duplicate_merger., With llm_provider='none', LLM is never called., For medium-confidence pairs, proposal contains merged content preview. (+45 more)

### Community 33 - "JobTracker"
Cohesion: 0.08
Nodes (40): JobStatus, JobTracker, Any, Track background job execution status for observability., Wrap a job function with tracking. Returns a no-arg callable for the scheduler., Snapshot of a single job's health., Thread-safe registry of background job execution outcomes., Yield True if this caller claimed the job, False if it was already running. An… (+32 more)

### Community 34 - "llm/__init__.py"
Cohesion: 0.08
Nodes (34): LLMAdapter, Abstract base class for LLM adapters., Send *prompt* to the LLM and return the raw response text. Returns ``None`` on…, Interface that all LLM backends must implement., _get_or_create_adapter(), get_adapter(), LLM adapter package — pluggable backends for background jobs., Build an adapter from the application settings. Returns ``None`` when the… (+26 more)

### Community 35 - "test_memory_engine.py"
Cohesion: 0.04
Nodes (34): _generate_title(), Generate a short title from the first line/sentence of content., Tests for the memory engine., whisper fires onboarding nudge exactly once when identity is empty., Identity protection must be active on the production call path (I3)., Reranker unavailable (fresh install, model downloading) must degrade to…, Desktop setup may cache the reranker after the server already started. The next…, Whisper may load an already-cached reranker, but must not download it. (+26 more)

### Community 36 - "Tauri Bundle Config"
Cohesion: 0.04
Nodes (46): app, security, windows, withGlobalTauri, build, beforeBuildCommand, frontendDist, bundle (+38 more)

### Community 37 - "test_whisper_out.py"
Cohesion: 0.10
Nodes (24): Find a transcript JSONL for a session ID across supported clients., _resolve_transcript_path(), _make_transcript(), _mock_client(), _outbox_records(), Tests for whisper-out: the PreCompact/SessionEnd hook is a pure /ingest/nudge…, SessionEnd hook POSTs {path, session_id} to /ingest/nudge and exits 0 — no…, Server unreachable -> exit 0 silently AND the path is queued in the outbox. (+16 more)

### Community 38 - "server_manager.py"
Cohesion: 0.06
Nodes (42): CalledProcessError, _called_process_error_output(), _find_manual_server_pids(), install_autostart(), install_launchd_agent(), install_systemd_service(), is_first_run(), _is_ormah_server_start_command() (+34 more)

### Community 39 - "test_confirmed_use_contract.py"
Cohesion: 0.06
Nodes (63): fts_only(), _make_nodes(), fixture, parametrize, Contract tests for issue #220: surfacing must not be confirmed use. Every…, Contract 5: the UI search route. This is the test that fails on clean…, Contract 6: whisper still mutates nothing after losing its flag. Whisper was…, Issue #220: _record_confirmed_use is atomic across its read-modify-write.… (+55 more)

### Community 40 - "open_bundle"
Cohesion: 0.08
Nodes (61): _add_member(), build_bundle(), BundleError, BundleInfo, _check_dest(), _iter_bundle_files(), _member_allowed(), open_bundle() (+53 more)

### Community 41 - "context_builder.py"
Cohesion: 0.10
Nodes (19): _first_sentence_truncate(), _gate_score(), _has_topical_overlap(), _prompt_log_snippet(), ndarray, Builds whisper context for involuntary recall injection., Absolute relevance signal for gating decisions. Gates answer "is anything here…, Return the first sentence of content, capped to max_len. (+11 more)

### Community 42 - "Database"
Cohesion: 0.10
Nodes (17): Database, Path, Insert one prompt payload shared by its candidate log rows., Run migrations for existing databases., Manages per-thread SQLite connections with WAL mode and serialized writes., Backfill content_fingerprint for rows whose file on disk hasn't changed. A row…, Add candidate-stage diagnostics without rebuilding feedback history., Record which synthetic pattern fired, so rot detection has a signal (#143). (+9 more)

### Community 43 - "IndexBuilder"
Cohesion: 0.09
Nodes (26): Row, IndexBuilder, Path, Update index for changed/new files. Returns (added, updated) counts., Builds and updates the SQLite index from markdown source files., Index or re-index a single file., The stored fingerprint + seq, read BEFORE _remove_node deletes the row. Only…, Index a single markdown file into the database (nodes + edges). (+18 more)

### Community 44 - "CLI Adapter Tests"
Cohesion: 0.08
Nodes (44): _mock_response(), Tests for the CLI adapter., Run the CLI with given args, returning (exit_code, stdout, stderr)., Create a mock httpx.Response., When cwd is missing, space should be None (no space key in body)., Nudge appears at the Nth prompt (default 10)., Nudge never appears when interval is 0., Each session_id gets its own counter. (+36 more)

### Community 45 - "_make_node_dict"
Cohesion: 0.08
Nodes (22): _make_engine_with_encoder(), _make_node_dict(), Standing rules use a typed applicability channel without biasing facts., The reranker must score the same context-enhanced query that search ran on, not…, Create a mock engine with a hybrid search encoder that returns a fixed vector., The injection gate cuts absolute signals (ce_absolute / raw_cosine), never the…, A weak query's least-bad match: blended ~0.9 (rank-relative top) but the cross-…, A genuinely relevant match under-ranked by the bi-encoder: the cross-encoder… (+14 more)

### Community 46 - "api.ts"
Cohesion: 0.10
Nodes (40): AdminTask, AgentInfo, BackupInfo, BackupStatus, CloudStatus, createBackup(), del(), fetchAdminTasks() (+32 more)

### Community 47 - "routes_admin.py"
Cohesion: 0.09
Nodes (43): _backup_service_from_request(), backup_status(), _backup_status_payload(), _backup_to_dict(), BackupSettingsUpdate, cloud_status(), create_backup(), _guard() (+35 more)

### Community 48 - "configure_llm"
Cohesion: 0.09
Nodes (19): _atomic_write(), configure_llm(), _cost_hint(), _enable_llm(), Read existing .env file into a dict., Write env dict to the global config file, preserving comments and ordering.…, Return a human-friendly monthly cost estimate for a model., Persist LLM policy. Never persist the actual API key value. (+11 more)

### Community 49 - "ContextBuilder"
Cohesion: 0.06
Nodes (22): ContextBuilder, Builds agent context from core memories., Whisper formatting: flat list, top 2 full, rest title-only., Whisper should return empty string on failure, not dump everything., Prompts of 2 chars or less (e.g. 'y', 'ok') should return empty., Prompts of 3+ chars should proceed normally., Whisper should respect max_nodes., Whisper outputs a flat ranked list — top 2 full, rest title+ID only. (+14 more)

### Community 50 - "ui/src/App.tsx"
Cohesion: 0.09
Nodes (31): App(), DEFAULT_EDGE_TYPES, Filters, PanelId, ThemeTransitionState, EDGE_TYPES, FilterDrawer(), Props (+23 more)

### Community 51 - "billing.py"
Cohesion: 0.10
Nodes (33): BaseException, NoReturn, BillingError, BillingErrorCode, BillingOffer, _canonical_account_id(), _canonical_uuid4(), CheckoutHandoff (+25 more)

### Community 52 - "test_ingest_extraction.py"
Cohesion: 0.05
Nodes (46): Split content into pieces at line (turn) boundaries; each piece is <=hard_cap.…, _split_for_extraction(), Extraction error classification: timeout/call-failure must not read as 'no…, If every chunk's call fails while a provider is configured, the whole…, Extracted memories below ingest_min_confidence are dropped before node creation., A single line (turn) longer than hard_cap is split into <=hard_cap pieces,…, An oversized turn between normal turns is split without dropping any turn or…, A variable payload against a fixed provider timeout is the bug. The hint must… (+38 more)

### Community 53 - "_insert_node"
Cohesion: 0.10
Nodes (25): _find_review_candidate(), Find a gated-out whisper candidate eligible for session-start review. Applies…, _insert_node(), _make_node_dict(), Tests for the review mechanism in build_whisper_context., was_injected=0 row within 7 days returns a candidate dict., Node with both was_injected=0 and was_injected=1 within 7 days is excluded., Tests for the Python-side filtering in _find_review_candidate. (+17 more)

### Community 54 - "test_main_lifespan_shutdown.py"
Cohesion: 0.07
Nodes (31): _FakeEngine, Blocks in backfill_embeddings until stop_event is set or 10s elapses. When…, _fake_lifespan_deps(), asyncio, fixture, Bounded scheduler shutdown + engine.shutdown() policy (Fix A / Fix D). Tests…, Fix D: when the fallback thread survives the join timeout, engine.shutdown()…, Fix A: when scheduler shutdown does not complete in time, engine.shutdown()… (+23 more)

### Community 55 - "FileStore"
Cohesion: 0.09
Nodes (28): FileStore, MemoryNode, Path, Move a node file to the deleted/ directory, stamping deleted_at atomically. The…, List tombstones in deleted/ as (node_id, deleted_at, path)., Hard-delete a tombstone from deleted/. Returns True if removed. Pass ``path``…, Load all nodes from disk., List all markdown file paths. (+20 more)

### Community 56 - "productBridge.ts"
Cohesion: 0.07
Nodes (56): ACTION_ICONS, errorMessage(), formatDate(), formatPrice(), LoginPurpose, operationIsActive(), operationLabel(), operationSuccessMessage() (+48 more)

### Community 57 - "dependencies"
Cohesion: 0.05
Nodes (41): graphology, graphology-layout, graphology-layout-forceatlas2, jsdom, lucide-react, sigma, @tauri-apps/api, dependencies (+33 more)

### Community 58 - "setup.py"
Cohesion: 0.04
Nodes (75): Extract project space from an encoded transcript directory name. Claude Code…, _space_from_encoded_dir(), _candidate_project_roots(), _claude_code_detected(), _cloud_recovery_paths(), CloudRecoveryPreflight, CloudRecoveryPreflightError, _codex_agents_target() (+67 more)

### Community 59 - "backup.py"
Cohesion: 0.08
Nodes (39): BackupInfo, BackupError, BackupInfo, BackupService, _count_backupable_markdown(), _count_markdown(), _directory_size(), _infer_user_node_id() (+31 more)

### Community 60 - "Design — ingest Batch budgeted on conversation length (ADR-0001 Amendment 3)"
Cohesion: 0.04
Nodes (39): Definition of done, File structure, Global Constraints, Ingest Batch Content Budget — Implementation Plan (overview), Out of scope (registered elsewhere, do not pick up), Rollout note, Tasks, The trap that will bite (+31 more)

### Community 61 - "test_account_auth_routes.py"
Cohesion: 0.18
Nodes (14): account_paths(), build_client(), FakeCloudClient, fixture, parametrize, Tests for token-free local account authentication adapters., test_account_email_rejects_unicode_line_separators(), test_logout_revokes_first_then_clears_locally_even_offline() (+6 more)

### Community 62 - "test_ingest.py"
Cohesion: 0.07
Nodes (25): _canned(), integration, parametrize, skipif, Tests for conversation ingestion: dry_run, confidence, truncation., Real claude_cli round-trip: mandatory schema must survive an actual `claude -p`…, A single oversized turn (no line breaks) larger than ingest_max_content_chars…, provider/model in the ledger must be the EFFECTIVE (resolved) values used by… (+17 more)

### Community 63 - "test_temporal_search.py"
Cohesion: 0.14
Nodes (13): _make_node(), mock_hybrid(), fixture, Tests for temporal query filters (created_after / created_before)., Temporal + type filters should combine with AND semantics., HybridSearch with mocked internals — no real DB or encoder., Run search with all three nodes returned by both retrievers., _run_search() (+5 more)

### Community 64 - "run_uninstall"
Cohesion: 0.08
Nodes (15): _claude_code_unwire(), Remove ormah agent definitions from ~/.claude/agents/., Remove ormah slash command definitions from ~/.claude/commands/., Remove the ormah instructions block from ~/.claude/CLAUDE.md., Remove Ormah while preserving zero-knowledge cloud recovery material., _remove_claude_agents(), _remove_claude_commands(), _remove_claude_md_block() (+7 more)

### Community 65 - "get_or_create_store_id"
Cohesion: 0.10
Nodes (30): get_or_create_store_id(), UUIDv4 per memory store, persisted at <memory_dir>/.store_id., LocalOperation, LocalOperationStatus, ProtectionOperationCoordinator, datetime, ProtectionOperation, StrEnum (+22 more)

### Community 66 - "test_spreading_activation.py"
Cohesion: 0.11
Nodes (38): _excerpt(), _feedback_id_suffix(), format_node(), format_node_with_neighbors(), format_search_results(), Any, Format graph data as human/agent-readable text., Format a single node as readable text. (+30 more)

### Community 67 - "test_account_billing_routes.py"
Cohesion: 0.10
Nodes (20): build_client(), client(), fake_client(), FakeCloudClient, fixture, parametrize, Tests for local account-linked billing handoffs., test_checkout_fails_closed_when_service_omits_authenticated_account_id() (+12 more)

### Community 68 - "CloudClient"
Cohesion: 0.09
Nodes (42): BaseTransport, _client_version(), CloudClient, CloudError, Any, RuntimeError, Small synchronous client for the metadata-only Ormah Cloud API., Return validated, display-safe subscription price metadata. (+34 more)

### Community 69 - "routes_protection.py"
Cohesion: 0.08
Nodes (62): backup_now(), bind_intent(), _cached_entitlement(), cancel_intent(), cancel_restore(), confirm_recovery_kit(), confirm_restore(), ConfirmRecoveryKitRequest (+54 more)

### Community 70 - "ok"
Cohesion: 0.05
Nodes (34): fail(), ok(), play_finale(), Shared output formatting for CLI and setup — matches install.sh visual style., Play a ~2.5s terminal animation: 'ormah' dissolves into a sphere. TTY only —…, Reset color detection cache (for testing)., Section header: \\n==> msg (bold)., Success: [ok] msg (green). (+26 more)

### Community 71 - "test_eval_recall/test_metrics.py"
Cohesion: 0.10
Nodes (36): compute_case_metrics(), f1_at_k(), false_negative_rate(), false_positive_present(), mrr(), precision_at_k(), Precision, recall, and related retrieval metrics for recall eval., Compute all metrics for a single (prompt, results) pair. injection_fired: True… (+28 more)

### Community 72 - "test cleanup auto ingested"
Cohesion: 0.13
Nodes (29): main(), _node_source(), plan_cleanup(), _print_table(), Path, Perform the destructive cleanup. Returns a process exit code. Steps:…, run_cleanup(), _FakeBackupService (+21 more)

### Community 73 - "run_auto_linker"
Cohesion: 0.11
Nodes (30): _get_watermark(), Return the seq of the last fully-processed node, or 0 if unset., Nodes with seq strictly greater than the watermark, ascending, bounded., Incrementally link nodes with seq above the watermark, judging candidate pairs…, run_auto_linker(), _select_nodes_after(), Pairs already checked should not trigger a second LLM call on re-run., Pairs classified as 'none' should be recorded in auto_link_checked. (+22 more)

### Community 74 - "cli_adapter.py"
Cohesion: 0.15
Nodes (26): _api(), _client(), cmd_ingest(), cmd_ingest_session(), cmd_node(), cmd_outdated(), cmd_recall(), cmd_remember() (+18 more)

### Community 75 - "CloudKeyError"
Cohesion: 0.12
Nodes (26): CloudKeyError, _ensure_recovery_kit_can_be_rewritten(), extract_recovery_kit_format_version(), extract_store_id_from_text(), install_store_id(), RuntimeError, Key lifecycle, store identity, and the recovery kit (E08 §1, §5). The key file…, Rotate the active identity without leaving recovery material behind. The… (+18 more)

### Community 76 - "test_merge_undo.py"
Cohesion: 0.08
Nodes (35): _create_node(), Tests for execute_merge and undo_merge operations., When remapping creates a self-loop, the edge is dropped., When remapping would duplicate an existing edge, it's skipped., execute_merge creates a record in merge_history., Undoing a merge restores the removed node., When merging nodes of different tiers, the higher-tier node is kept., Undoing a merge restores the removed node's original edges. (+27 more)

### Community 77 - "test_seq_fingerprint.py"
Cohesion: 0.10
Nodes (35): _make_node(), Conditional seq allocation driven by a persisted content fingerprint (#126)., auto_cluster dual-writes `space`: straight into SQLite AND into the markdown., Content feeds the embedding and the judge prompt., Type is shown to the LLM judge., Tags feed FTS, never the linker., A row whose file on disk no longer matches its file_hash has a pending reindex.…, A row whose file matches its hash is stamped, so the upgrade does not requeue… (+27 more)

### Community 78 - "hippocampus.py"
Cohesion: 0.12
Nodes (21): _detect_space(), _file_hash(), HippocampusHandler, _ingest_file(), _matches_ignore(), FileSystemEventHandler, Path, Hippocampus — real-time file watching & auto-ingestion of .md files. (+13 more)

### Community 79 - "test feedback schema"
Cohesion: 0.11
Nodes (34): _index_exists(), _make_db_without_new_tables(), _make_legacy_affinity_db(), Path, Tests for whisper_log, affinity, and review_log schema additions., Feedback is capped per whisper event, not per whole session., Create a DB, init schema, then drop the three new tables to simulate an older…, Calling _migrate() on an already-migrated DB must not raise. (+26 more)

### Community 80 - "_make_titled_hybrid"
Cohesion: 0.06
Nodes (34): _make_titled_hybrid(), A node with valid_until in the future should not be filtered., With 10 results in both lists, min-max normalization should produce a score…, Two results at adjacent ranks in both lists (spread ~1.6%) should use max-norm…, A single result should use max-norm fallback and score > 0.7., Question query with FTS and vec disagreement — semantic match should still win…, Create a HybridSearch with titled nodes and optional content lengths., A node with the query term in its title scores higher than one with it only in… (+26 more)

### Community 81 - "llm_cancel.py"
Cohesion: 0.19
Nodes (11): aborted(), epoch_changed(), note_call_finished(), note_call_started(), Single authority for LLM call cancellation (ADR-0004 slice 2 redesign).…, This call's era AND whether the world is cancelled — from ONE critical section., Was THIS call's era superseded? Immune to a later resume(), unlike…, ``epoch_changed(gen) or cancelled`` — as one atomic read, never two. (+3 more)

### Community 82 - "detect_space_from_cwd"
Cohesion: 0.16
Nodes (19): detect_space_from_cwd(), detect_space_from_dir(), Shared space detection for CLI and MCP adapters., Detect the project space from an explicit directory path. Tries git repo…, Detect the project space from the current working directory. Tries git repo…, Resolve space: explicit flag > ORMAH_SPACE env > cwd detection., resolve_space(), Tests for shared space detection. (+11 more)

### Community 83 - "validate_case"
Cohesion: 0.11
Nodes (13): CorpusError, load_corpus(), Exception, Path, Load and validate whisper eval corpus files (JSONL format)., Raised on corpus file or validation errors., Load a JSONL corpus file. Skips blank lines. Validates each case., Validate a single corpus case. Raises CorpusError on structural issues. (+5 more)

### Community 84 - "run_forgetting"
Cohesion: 0.15
Nodes (43): Soft-delete dead-weight archival nodes, then purge expired tombstones., run_forgetting(), ConnectRequest, _archival_count(), _break(), _enable(), _exists(), _make_archival_recent() (+35 more)

### Community 85 - "llm_client.py"
Cohesion: 0.09
Nodes (30): _get_or_create_ingest_adapter(), ingest_llm_generate(), ingest_provider_configured(), Shared LLM facade for background tasks. All callers import ``llm_generate``…, Ingest path: PROPAGATE LlmCancelledError. The engine maps it to a provider-wide…, True when a server-side extraction adapter is available (ingest provider !=…, Clear the cached adapters (useful for test isolation)., reset_adapter() (+22 more)

### Community 86 - "get_fastembed_cache_dir"
Cohesion: 0.11
Nodes (21): get_fastembed_cache_dir(), get_model_cache_dirname(), is_model_cached(), Path, Helpers for locating and inspecting the shared Ormah model cache., Return the effective shared model cache directory., Resolve a fastembed model name to its on-disk cache directory name., Return True when the model's expected fastembed cache directory exists. (+13 more)

### Community 87 - "test pair batch"
Cohesion: 0.09
Nodes (20): Issue #87: pair batching — settings, timeout hint, batch module., Council R2: zero-usable gets ONE half-size probe, never the full tree., The bound applies to ZERO_USABLE only — unparseable keeps today's tree., Council C1: an outage must not iterate the whole collected list., _settings(), test_batching_settings_defaults(), test_explicit_k_overrides_settings(), test_k1_is_a_pure_map_over_judge_single() (+12 more)

### Community 88 - "src/types.ts"
Cohesion: 0.09
Nodes (28): searchNodes(), formatDate(), InsightsPanel(), Props, Props, SearchResults(), PanelId, Props (+20 more)

### Community 89 - "Recomendações para o Ormah como projeto open source"
Cohesion: 0.04
Nodes (45): 10. Tornar documentação operacional confiável, 11. Tornar eval reproduzível, 12. Revisar os 18 commits upstream antes de novas features locais, 13. Durable Mutation Coordinator, 14. Embedding Index Generations, 15. Durable Work Ledger, 16. Memórias com evidência e validade por afirmação, 17. Retrieval Policy traceável (+37 more)

### Community 90 - "TestSafeBoundary"
Cohesion: 0.06
Nodes (16): A trailing pair with NO completion signal (no stop_reason field) is not safe…, tool_use followed by a text assistant must form ONE pair, not fragment. The…, A trailing tool-only assistant (no text) leaves the pair pending (known…, A multi-record assistant response at EOF must not be committed mid-stream. The…, Once the next user turn arrives, the full multi-record response is one safe…, A terminal stop_reason (Claude Code) closes the response immediately — the safe…, A multi-record response (tool_use then end_turn) is one safe pair, never split…, If the user interrupts a non-terminal response, the next user turn still closes… (+8 more)

### Community 91 - "CreateNodeRequest"
Cohesion: 0.03
Nodes (119): _apply_consolidation(), Create a consolidated node, link originals, and demote them to archival.…, Auto-demote working nodes whose FSRS retrievability drops below threshold., run_decay(), Iterate all nodes, compute weighted importance, persist changes., run_importance_scoring(), CreateNodeRequest, BaseModel (+111 more)

### Community 92 - "forgetting_manager.py"
Cohesion: 0.13
Nodes (30): _archival_rows(), _aware(), _backfill_legacy_archived_at(), _cap_guard(), _connectivity(), _eligibility_guard(), _evaluate_protection(), _forget_score() (+22 more)

### Community 93 - "restore.py"
Cohesion: 0.05
Nodes (71): RestoreProgress, Build a BackupService from a Settings-like object., Result of restoring a memory backup., RestoreResult, service_from_settings(), _candidate_blobs(), cleanup_abandoned_cloud_restores(), CloudRestoreError (+63 more)

### Community 94 - "run_setup_json"
Cohesion: 0.11
Nodes (25): AgentDescriptor, configure_agent_maintenance(), detect_clients(), _detected_agents(), _get_agent(), _persist_env_delta(), Apply this setup action's changes without overwriting concurrent writers., Ask whether to enable automatic agent-backed maintenance. Returns True if… (+17 more)

### Community 95 - "TestSubmitFeedbackBasic"
Cohesion: 0.11
Nodes (5): _insert_review_log(), _insert_whisper_log(), Tests for engine.submit_feedback and POST /agent/feedback route., TestSubmitFeedbackBasic, TestSubmitFeedbackRoute

### Community 96 - "test relevance runner"
Cohesion: 0.15
Nodes (24): _default_engine(), _labels_for(), main(), Any, Path, In-context relevance-gate eval (the ship gate). Run pre-merge with a live…, Return the list of provenance labels the real extractor emits for a snippet., Construct the real MemoryEngine the way the codebase does (see… (+16 more)

### Community 97 - "_NeverEofProc"
Cohesion: 0.11
Nodes (4): _FakeProc, _NeverEofProc, A child whose pipes NEVER reach EOF — models the setsid grandchild that…, Minimal fake Popen result. Mirrors real subprocess.Popen semantics closely…

### Community 98 - "test_db_concurrency.py"
Cohesion: 0.36
Nodes (7): _init_db(), Concurrency tests for the thread-local Database connection model., Regression: vec0 module is loaded per connection; a fresh thread must still be…, A read on thread B returns promptly while thread A holds a write tx., test_each_thread_gets_distinct_connection(), test_read_during_write_does_not_block(), test_vector_search_works_from_worker_thread()

### Community 99 - "run_whisper_eval"
Cohesion: 0.13
Nodes (13): _aggregate(), _aggregate_by_category(), PromptResult, Whisper eval runner — seeds DB, calls full pipeline, collects metrics per…, Aggregate metrics across prompt results. Noise and non-noise are separated., Run the whisper eval pipeline over *cases*., run_whisper_eval(), integration (+5 more)

### Community 100 - "EdgeType"
Cohesion: 0.18
Nodes (28): EdgeType, _backdate(), _create(), Mutation-stamping guarantees (Sync v1 Step 0). Every content mutation must…, Create a node with auto-linking suppressed, return its id., Phase-2 repaired defines edges must live in the self node's markdown so they…, Parse the tombstone file for a node from deleted/., _reset_adapter() (+20 more)

### Community 101 - "start_scheduler"
Cohesion: 0.09
Nodes (26): BackgroundScheduler, Vector-store reconciliation job: backfill missing embeddings (#32)., Reconcile the vector store. Raises if the store is left incomplete. Unlike the…, run_embedding_backfill(), datetime, Event, APScheduler job registration for background processing., One shared factor for all four jobs, so distinct nominal offsets stay distinct… (+18 more)

### Community 102 - "whisper/cli.py"
Cohesion: 0.11
Nodes (25): _check_fail_below(), cmd_eval_whisper_import_labels(), cmd_eval_whisper_mine(), _make_engine(), CLI handler for `ormah eval whisper run`., Parse 'f1=0.65,suppression=0.90' and check thresholds. Returns 1 if any fails.…, _connect_ro(), _draft_expected() (+17 more)

### Community 103 - "test_cloud_cli.py"
Cohesion: 0.14
Nodes (22): cloud_paths(), fixture, CLI tests for the `ormah cloud` group., `ormah cloud kit` is the recovery path when init/rotate is interrupted between…, Fresh-machine import must adopt the kit's store id, not mint a new one — the…, Point every cloud path at tmp and return the key path., A damaged store_id line must abort the whole import before any key material is…, _run() (+14 more)

### Community 104 - "test_routes.py"
Cohesion: 0.08
Nodes (14): health(), Tests for API routes., CH2: with no scheduler, a degraded fallback makes /admin/health degraded., Inverse: a healthy fallback (flag False) leaves health ok., Issue #90 (dev council follow-up): a Phase 1 with a broken finder must still…, CR2: scheduler present + embedding_backfill last run failed -> health degraded., A later success after an error leaves health ok., test_health_degraded_when_no_scheduler_and_fallback_failing() (+6 more)

### Community 105 - "desktop ui package"
Cohesion: 0.07
Nodes (26): dependencies, framer-motion, react, react-dom, devDependencies, @types/react, @types/react-dom, typescript (+18 more)

### Community 106 - "TierManager"
Cohesion: 0.23
Nodes (7): MemoryNode, Manages tier transitions and enforces the core memory cap., Promote a node to a higher tier. Returns True if promoted., Demote a node to a lower tier. Returns True if demoted., If core nodes exceed the cap, demote least-accessed ones to working. Nodes in…, TierManager, Tier

### Community 107 - "test_run_stats.py"
Cohesion: 0.16
Nodes (13): Issue #90: maintenance runs return a stats dict., At the 1440-minute defaults the nominal offsets (5/15/30/45) are unscaled —…, Issue #90 council R3 finding 2: scaling each job by ITS OWN interval let jobs…, Issue #90 council R2 finding 1: a DB/encoder failure inside the finder must not…, Same as above for duplicate_merger's finder (also only reachable via…, _spy_add_job(), test_auto_linker_returns_stats(), test_conflict_detector_stats_shape() (+5 more)

### Community 108 - "parse_transcript"
Cohesion: 0.16
Nodes (8): parse_transcript(), Parse a supported JSONL transcript into cleaned conversation text. Reads line…, Path, Write a list of dicts as JSONL to a temp file and return the path., safe_* must exclude a dangling user turn; raw fields still include it., A response truncated by max_tokens (or refused) is complete — it must close the…, TestParseTranscript, _write_jsonl()

### Community 109 - "test_server_manager.py"
Cohesion: 0.07
Nodes (19): Tests for server lifecycle helpers: port-conflict detection and launchd plist., A ThrottleInterval backstops genuine crash loops., A healthy Ormah listener makes a duplicate foreground start a no-op., A foreign listener must make the supervisor retry instead of going dormant., A bound, listening socket is reported as in use., When the port is free, uvicorn is launched as normal., A port with no listener is reported as free., An IPv6 host literal must not fail the pre-flight probe. (+11 more)

### Community 110 - "cmd_whisper_store"
Cohesion: 0.12
Nodes (20): cmd_whisper_store(), _drain_nudge_outbox(), _outbox_lock(), _queue_nudge(), Drop only this transcript's key; delete the file once it is empty (council…, Lock a STABLE file, never the outbox itself. flock locks an inode. The drain…, Append a boundary event durably and return its record id. Called BEFORE any…, Atomic rewrite. Caller MUST hold _outbox_lock(). (+12 more)

### Community 111 - "GraphIndex"
Cohesion: 0.09
Nodes (14): GraphIndex, Any, Query nodes by created timestamp, ordered by created DESC. Returns up to…, Full-text search using FTS5. Uses AND semantics for multi-token queries (all…, Graph queries on the SQLite index., Fetch multiple nodes in a single query, keyed by ID., Fetch tags for multiple nodes in a single query, keyed by node ID., Get neighbors up to `depth` hops using recursive CTE. (+6 more)

### Community 112 - "HybridSearch"
Cohesion: 0.15
Nodes (12): HybridSearch, Combines FTS5 full-text search with sqlite-vec vector search., _make_node(), Unit tests for HybridSearch title boost score capping. Verifies that…, Multiple query tokens matching title → high title_bonus, but still capped., Even with tier boost + recency + access, final_score capped at 1.0., Build a minimal node dict matching GraphIndex.get_nodes_batch output., Question queries disable title boost, so no cap needed (but shouldn't break). (+4 more)

### Community 113 - "setup_logging"
Cohesion: 0.13
Nodes (21): LogRecord, _JSONFormatter, Path, Logging configuration — text or JSON format., Configure the root logger. Args: log_format: ``"text"`` for human-readable…, Redact known API-key values from log text., Redact strings inside JSON log extras without changing non-secret types., Text formatter that redacts API-key values from the final rendered line. (+13 more)

### Community 114 - "CloudCryptoError"
Cohesion: 0.22
Nodes (23): Identity, Recipient, CloudCryptoError, decrypt_bytes(), encrypt_bytes(), generate_identity(), identity_from_str(), identity_to_str() (+15 more)

### Community 115 - "memory_engine.py"
Cohesion: 0.07
Nodes (42): main(), Path, sha_map(), step(), Create a backup when automatic backups are enabled and due., run_auto_backup(), is_maintenance_due_signal(), Shared wording for the agent-backed maintenance whisper signal. (+34 more)

### Community 116 - "extract_time_params"
Cohesion: 0.21
Nodes (7): extract_time_params(), Parse lightweight time references and return…, Tests for extract_time_params (bounded time windows)., last 2 weeks' uses rolling previous-period: 4w ago → 2w ago., last 1 week' (N=1) extends to now, not rolling., last 3 months' uses rolling: 6m ago → 3m ago., TestTimeExtraction

### Community 117 - "test_routes_admin_run_task.py"
Cohesion: 0.18
Nodes (9): The manual task-trigger routes must not start a job that is already running,…, A manual trigger during the scheduled run used to start a second concurrent run…, The route returned {'status': 'completed'} unconditionally — a run that blew up…, run-all calls the runners directly too — same hole., The guard is only atomic against a SHARED tracker. It was created inside the…, test_lifespan_always_creates_a_job_tracker_even_if_the_scheduler_fails(), test_run_all_skips_a_task_that_is_already_running(), test_run_task_rejects_a_job_that_is_already_running() (+1 more)

### Community 118 - "PromptIntent"
Cohesion: 0.07
Nodes (21): PromptIntent, Result of classifying a user prompt., TestPromptIntent, Precision helpers should favor the most relevant whisper candidate., Context-enhanced search using recent prompts., Underspecified follow-up prompts should use recent context in search., Fully specified prompts should not be polluted by recent context., Without recent_prompts, search query should be the raw prompt. (+13 more)

### Community 119 - "ControlledEncoder"
Cohesion: 0.13
Nodes (13): ControlledEncoder, ndarray, Test classification decisions with controlled cosine similarities., When prompt vector is identical to an archetype, it should match., When prompt doesn't match any archetype, return general., Conversational only applies when it's the sole match., If conversational + temporal both match, conversational is removed., Conversational should win when other matches are far below its score. (+5 more)

### Community 120 - "mcp_adapter.py"
Cohesion: 0.12
Nodes (23): AsyncClient, Server, _coerce_list(), create_mcp_server(), _dispatch(), _format_maintenance_batches(), _format_timeout_error(), _handle_error() (+15 more)

### Community 121 - "compilerOptions"
Cohesion: 0.08
Nodes (23): compilerOptions, allowImportingTsExtensions, baseUrl, isolatedModules, jsx, lib, module, moduleResolution (+15 more)

### Community 122 - "background/__init__.py"
Cohesion: 0.12
Nodes (18): main(), CLI: python -m eval.maintenance.cli {mine|run|report} ... Local A/B eval gate…, _connect_ro(), mine_pairs(), Mine auto-link candidate pairs from a production store, read-only (#87 eval).…, agreement(), Agreement metrics for the single-vs-batched maintenance eval (#87 gate). Gate…, _load_pairs() (+10 more)

### Community 123 - "seed_case"
Cohesion: 0.14
Nodes (14): clear_eval_db(), _parse_dt(), datetime, Seed the isolated whisper eval DB with memories from a corpus case., Parse an ISO/RFC3339 datetime string into a timezone-aware UTC datetime. Uses…, Remove all nodes from the eval DB and file store. When *preserve_self* is True,…, Return a datetime for *field* from corpus memory *mem*. Supported formats: -…, Clear eval DB and seed with memories from *case*. Memories are inserted with… (+6 more)

### Community 124 - "parser.py"
Cohesion: 0.09
Nodes (27): main(), Measure the realised raw span per slice under the content budget, to size the…, _assistant_is_terminal(), _coerce_entry(), _conversation_from_turns(), _extract_assistant_text(), extract_user_prompts(), _extract_user_text() (+19 more)

### Community 125 - "test_eval_recall/test_report.py"
Cohesion: 0.19
Nodes (21): _arrow(), _bar(), format_report(), load_previous_run(), Path, Format recall eval reports and write results files., Write latest.json and append to history.jsonl., Return the last comparable history entry, or None if none exists. Runs at a… (+13 more)

### Community 126 - "CorpusError"
Cohesion: 0.19
Nodes (17): CorpusError, load_corpus(), Exception, Path, Load and validate eval corpus files (JSONL format)., Raised on corpus file errors., Load a corpus JSONL file. Skips header lines. Returns list of cases. Raises…, Validate a single corpus case. Raises CorpusError on structural issues. (+9 more)

### Community 127 - "compute whisper health"
Cohesion: 0.24
Nodes (18): compute_whisper_health(), datetime, Whisper effectiveness metrics derived from whisper_log + affinity. Read-only…, Return whisper coverage/precision over all_time and last_7d windows. ``now`` is…, _window(), _db(), _feedback(), _inject() (+10 more)

### Community 128 - "compilerOptions"
Cohesion: 0.09
Nodes (22): compilerOptions, allowImportingTsExtensions, forceConsistentCasingInFileNames, isolatedModules, jsx, lib, module, moduleDetection (+14 more)

### Community 129 - "desktop/ui/src/App.tsx"
Cohesion: 0.17
Nodes (22): App(), goGraph(), retrySetup(), Phase, TitleBar(), AgentInfo, InstallPanel(), connect() (+14 more)

### Community 130 - "Lifecycle cluster — issue dossier"
Cohesion: 0.06
Nodes (31): 1. Are "assigned to me" and "the lifecycle work" the same thing?, #209 — the pending merge-proposal queue is unbounded `bug`, #218 — `signals.strength` has no variance in any channel `bug`, #219 — nothing reclaims disk `enhancement`, #220 — separate surfaced results from confirmed memory use `bug`, #221 — bound stability reinforcement and add a per-day cooldown `bug`, #222 — stop importance from permanently blocking working-tier decay `bug`, #223 — reversible promotion + the seven-day initial lease `enhancement` (+23 more)

### Community 131 - "extract_json"
Cohesion: 0.06
Nodes (48): _llm_classify_link(), Automatic edge creation based on embedding similarity., Render one candidate pair for a batched link prompt (#87)., Ask LLM to classify the relationship between two nodes. Returns a dict with…, _render_link_pair(), _llm_check_conflict(), Detect contradictions between memory nodes., Render one candidate pair for a batched conflict prompt (#87). (+40 more)

### Community 132 - "find_rotted_patterns"
Cohesion: 0.10
Nodes (28): find_rotted_patterns(), _proposed_action(), datetime, Detect synthetic-prompt patterns that stopped matching (#143). The #134…, Stable text derived ONLY from the pattern — this string is the dedup key. Never…, Propose corrections for synthetic patterns that went quiet (#143). Proposes,…, A live pattern that matched before and has now gone quiet., Live patterns whose last match predates the rot window. Pure read. Rot is… (+20 more)

### Community 133 - "MemoryEngine facade"
Cohesion: 0.12
Nodes (21): Eval gating deliberately excluded from CI, ContextBuilder, FileStore, GraphIndex, IndexBuilder, Markdown is the source of truth, MemoryEngine facade, Write path (+13 more)

### Community 134 - "APScheduler background scheduler"
Cohesion: 0.13
Nodes (21): Connection (typed weighted edge), Core cap enforcement (50 nodes), CreateNodeRequest, EdgeType and activation factors, FSRS stability field, MemoryNode, Proposal (merge/conflict/decay), Tier (core / working / archival) (+13 more)

### Community 135 - "test_hybrid_search.py"
Cohesion: 0.10
Nodes (19): Tests for hybrid search scoring mechanics. These test the RRF fusion, threshold…, A node with valid_until in the past should be completely excluded from results., All identity tokens should be in the stop words list., If vector search fails, results should still come from FTS alone., Should never return more results than the limit., When tags filter is provided, get_tags_batch should be called once., Verify that FTS query uses bm25 column weights (title 10x, tags 5x). This is an…, FTS5 with porter stemmer matches morphological variants (live → lives). (+11 more)

### Community 136 - "_sanitize_fts_query"
Cohesion: 0.14
Nodes (14): Convert natural language query to FTS5-compatible queries. Returns a list of…, _sanitize_fts_query(), what is the user's name' should inject about_self into FTS tokens., grapes' has no identity token — should NOT inject about_self., does the user like grapes' should inject about_self., A query with only identity tokens (all stopped) should fall back to raw tokens…, my email' should inject about_self alongside 'email'., FTS query for 'user capitalism' should strip 'user' and produce just… (+6 more)

### Community 137 - "configure_codex_mcp"
Cohesion: 0.09
Nodes (17): _codex_wire(), configure_codex_mcp(), install_codex_agents(), install_codex_md(), Remove ormah entry from ~/.codex/config.toml., Remove a top-level TOML table block while preserving surrounding content., Write or update the Ormah MCP entry in ~/.codex/config.toml., Register Ormah MCP server in Codex config. (+9 more)

### Community 138 - "_is_ormah_hook"
Cohesion: 0.11
Nodes (11): _install_hooks(), _is_ormah_hook(), _merge_hooks(), True when a hook entry is one Ormah installs (argv-aware, not substring).…, Merge Ormah hook groups into an existing hooks dict, preserving co-tenants. For…, Remove Ormah hook entries while preserving every untouched matcher. Returns the…, Read a JSON hooks config, merge Ormah hooks preserving co-tenants, write back.…, _strip_ormah_hooks() (+3 more)

### Community 139 - "local_auth.py"
Cohesion: 0.14
Nodes (18): load_or_create_local_admin_token(), Path, Request, Owner-only capability authentication for sensitive local API routes., Load this installation's local API capability, creating it mode 0600., Reject sensitive requests that did not originate on this machine., Authenticate a native local caller without exposing the cloud account token., require_local_admin() (+10 more)

### Community 140 - "test_main_backfill_fallback.py"
Cohesion: 0.08
Nodes (32): _CancellableEngine, _monkeypatch_run_embedding_backfill(), fixture, _QuickEngine, Scheduler-independent embedding backfill fallback (#32, council C2/CH1/CH2).…, CH1: a second start while one is alive does not spawn a second thread., CH1: _stop_backfill_fallback stops a permanently-failing fallback., Completes immediately with no missing nodes. (+24 more)

### Community 141 - "Whisper pipeline (involuntary recall)"
Cohesion: 0.13
Nodes (20): Whisper path, Whisper candidate diagnostics and retention, Flat markdown whisper formatter, Prompt intent classification, Selective query enhancement for follow-ups, Session prompt ring buffer, Topic-shift skip, Whisper pipeline (involuntary recall) (+12 more)

### Community 142 - "configure_codex_hooks"
Cohesion: 0.14
Nodes (11): configure_codex_hooks(), _enable_codex_feature(), Write Codex hook config to ~/.codex/hooks.json and enable the feature flag., Insert or update a key within a top-level TOML table., Remove a key from a top-level TOML table., Enable a Codex feature flag in ~/.codex/config.toml., _remove_toml_table_key(), _upsert_toml_table_key() (+3 more)

### Community 143 - "auto_linker edge-write hardening — Overview"
Cohesion: 0.08
Nodes (19): auto_linker edge-write hardening — Overview, Background — what was diagnosed (2026-07-13), File structure, Setup (do this once, before Task 1), Task index, Verified facts that shape this plan (do not re-litigate), PR A — Idempotent edge writes (closes #117), Task 1: `_apply_edge` becomes idempotent (+11 more)

### Community 144 - "compute_affinity_boost"
Cohesion: 0.09
Nodes (25): batch_fetch_affinity(), compute_affinity_boost(), ndarray, Affinity boost module for the adaptive feedback loop. Computes per-node score…, Fetch all affinity rows for a list of node_ids in a single query. Returns a…, Compute the affinity boost for a candidate node. For each affinity row, a…, _insert_affinity_row(), _make_affinity_db() (+17 more)

### Community 145 - "account.py"
Cohesion: 0.09
Nodes (40): AccountStatus, _close_owned(), get_account_status(), logout_account(), LogoutResult, Any, Shared local account application service for CLI and desktop adapters., Verify one OTP, persist the token privately, and update live settings. (+32 more)

### Community 146 - "recall/cli.py"
Cohesion: 0.14
Nodes (17): _check_fail_below(), _check_regression(), cmd_eval_recall_export_for_labeling(), cmd_eval_recall_run(), _corpus_files_for_label(), _make_engine(), Path, CLI handlers for `ormah eval recall` commands. (+9 more)

### Community 147 - "serialized_memory_job"
Cohesion: 0.08
Nodes (25): Automatic space/cluster assignment for unassigned nodes., _cluster_signature(), _consolidate_cluster(), _find_consolidation_clusters(), Background job: consolidate clusters of similar working-tier memories via LLM., Find clusters of similar working memories and consolidate via LLM., Consolidate a single cluster using LLM summarization., Content signature of a cluster: changes if any member's id/title/content/… (+17 more)

### Community 148 - "test_stats.py"
Cohesion: 0.14
Nodes (17): _log_decision(), _log_whisper(), Tests for the canonical /stats endpoint., Candidates that were logged but not injected don't count as used., GET /agent/clients returns the agent list with detection and wired status., silence_rate + injection_rate must cover all prompts., Insert a synthetic whisper_log row mirroring context_builder's writer., One whisper call writes several candidate rows sharing logged_at. The counter… (+9 more)

### Community 149 - "check_entitlement"
Cohesion: 0.19
Nodes (18): check_entitlement(), EntitlementStatus, Enum, str, Return ``active|grace|expired|none`` without propagating refresh failures., cache_path(), FakeClient, Exception (+10 more)

### Community 150 - "visual.ts"
Cohesion: 0.23
Nodes (13): applyAppearance(), buildGraph(), NOTE: store the domain node type under `nodeType`, NOT `type` — sigma, seedPosition(), computeSelfRoles(), displayNodeSize(), edgeColor(), nodeLabel() (+5 more)

### Community 151 - "_find_link_candidates"
Cohesion: 0.17
Nodes (8): _find_link_candidates(), Find node pairs that need link classification. Returns up to *limit* pairs as…, test_find_candidates_uses_window_without_advancing(), Tests for the run_maintenance two-call protocol., Create n nodes with similar content and return their IDs., _seed_similar_nodes(), TestApplyMaintenanceResults, TestFindLinkCandidates

### Community 152 - "routes_ui.py"
Cohesion: 0.19
Nodes (14): get_graph(), get_insights(), get_node_detail(), get, Request, UI API routes for the web graph explorer., Search nodes for the UI, returning structured results. Uses the same hybrid…, Graph data for the explorer. Default (no ``space``): the *active graph* — non-… (+6 more)

### Community 153 - "seed_case"
Cohesion: 0.21
Nodes (17): clear_eval_db(), datetime, Seed the isolated recall eval DB with memories from a corpus case., Return a created datetime for *mem*, or None for 'now'. Supports ``created``…, Clear eval DB and seed with memories from *case*. Memories are inserted with…, Remove all nodes from the eval DB and file store., seed_case(), _seed_created() (+9 more)

### Community 154 - "conftest.py"
Cohesion: 0.16
Nodes (18): _clean_llm_cancel_epoch(), db(), engine(), file_store(), _is_real_ormah_path(), _is_relative_to(), isolate_fastembed_cache(), _isolate_settings_from_global_env() (+10 more)

### Community 155 - "test_cli_account.py"
Cohesion: 0.16
Nodes (12): account_paths(), FakeClient, fixture, parametrize, _run(), test_account_settings_are_loaded_from_environment(), test_login_keeps_credentials_when_entitlement_refresh_is_offline(), test_login_persists_credentials_without_rewriting_unrelated_lines() (+4 more)

### Community 156 - "TestSyntheticPromptEndpoint"
Cohesion: 0.13
Nodes (8): A machine-generated turn is skipped at the /agent/whisper boundary, BEFORE any…, matches everything and is falsy — the guard must test `is not None`. Truthiness…, Kill-switch coverage: it was dropped in 566fe3a when the guard moved., Rot detection is impossible without knowing WHICH pattern matched (#143)., Only silent_synthetic rows carry a pattern; everything else stays NULL., Dead sessions are evicted from _session_buffers on access (I12)., TestSessionBufferEviction, TestSyntheticPromptEndpoint

### Community 157 - "Ormah Desktop (Tauri v2 app)"
Cohesion: 0.13
Nodes (18): CI desktop job (Tauri + UI), uv sidecar download step, Bundled runtime (uv sidecar installs ormah from PyPI), Menubar tray presence (weekly whispers-used counter), Ormah Desktop (Tauri v2 app), desktop-product-bridge (trusted recovery handoff), Frozen ormah-server sidecar binaries directory, Desktop bootstrap UI HTML shell (+10 more)

### Community 158 - "TestReleaseVersionVerification"
Cohesion: 0.18
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

### Community 162 - "stored_or_encoded"
Cohesion: 0.15
Nodes (17): embedding_text(), Canonical probe text for embeddings. Single source of truth: every vector in…, Build text for embedding. Truncates content to avoid topic averaging in long…, Vector storage and search using sqlite-vec., Return the stored embedding for *node_id*, re-encoding only if it is missing.…, stored_or_encoded(), _CountingEncoder, _ExplodingEncoder (+9 more)

### Community 163 - "compilerOptions"
Cohesion: 0.11
Nodes (17): compilerOptions, esModuleInterop, forceConsistentCasingInFileNames, lib, module, moduleResolution, noEmit, skipLibCheck (+9 more)

### Community 164 - "Review Relevance Is Not Confirmed Use — Implementation Plan"
Cohesion: 0.33
Nodes (5): After both tasks, File Structure, Global Constraints, Review Relevance Is Not Confirmed Use — Implementation Plan, Tasks

### Community 165 - "normalize_conflict_type"
Cohesion: 0.19
Nodes (14): normalize_conflict_type(), normalize_link_type(), Normalize LLM responses to canonical edge/conflict types., Map a raw LLM conflict type to a canonical value. Unknown values default to…, Map a raw LLM link type to a canonical value. Unknown values default to…, Tests for LLM response normalization functions., test_canonical_conflict_types_pass_through(), test_canonical_link_types_pass_through() (+6 more)

### Community 166 - "test_llm_cancel.py"
Cohesion: 0.11
Nodes (15): Re-admit NEW calls after a RECOVERABLE cancel (the watcher's startup rollback).…, resume(), _clean_epoch(), fixture, Epoch semantics for LLM cancellation (ADR-0004 slice 2 redesign). These tests…, The watcher logs this count; it replaces the old "processes terminated" number., R4 regression. A resume() re-admits NEW calls; it must never un-cancel a call…, A final cancel must not outlive its lifespan: the llm_client adapter caches are… (+7 more)

### Community 167 - "run_eval"
Cohesion: 0.19
Nodes (16): _aggregate(), _eval_case(), EvalResult, Recall eval runner: orchestrates per-case seeding, retrieval, and scoring., Compute aggregate metrics across all prompt results. Returns None for each…, Run the recall eval pipeline over *cases*. Returns EvalResult with per-case and…, Seed and evaluate a single corpus case., run_eval() (+8 more)

### Community 168 - "Review relevance is not confirmed use"
Cohesion: 0.15
Nodes (12): Accepted consequence — the legacy fallback, Blast radius, Related, Review relevance is not confirmed use, Scope, Tests, The defect, The fix (+4 more)

### Community 169 - "MemoryEngine"
Cohesion: 0.06
Nodes (20): MemoryEngine, Soft-delete a node only if ``guard(conn)`` still holds inside the write txn.…, Record a whisper call skipped because the prompt was machine-generated. Called…, Get compact whisper context for involuntary recall injection., Main facade: remember(), recall(), connect(), context()., List recent merge history., List recent audit log entries, optionally filtered by node_id or operation., Return non-expired identity-linked memories for a project/global scope. (+12 more)

### Community 170 - "_claude_code_wire"
Cohesion: 0.18
Nodes (10): _claude_code_wire(), install_claude_agents(), install_claude_commands(), Install ormah custom agent definitions into ~/.claude/agents/., Install ormah slash command definitions into ~/.claude/commands/., A stale enabled flag must not cost the user the whisper., Deliberate: the CLI hooks are global and serve every other project., Fail-open: an unparseable config must not silently disable the whisper. (+2 more)

### Community 171 - "test_protection_routes.py"
Cohesion: 0.09
Nodes (13): _poll(), parametrize, The only signal a second machine leaves is a snapshot this device did not…, Not knowing what the cloud holds must never break protection status., test_long_operations_return_202_and_poll_safe_results(), test_malformed_recovery_digest_is_rejected_before_service_work(), test_mutation_routes_forbid_extra_fields(), test_remote_degrades_without_taking_the_panel_down() (+5 more)

### Community 172 - "test_scoring_signals.py"
Cohesion: 0.12
Nodes (24): _lifecycle(), _make_node(), fixture, Tests for recency, access frequency, and tier scoring signals in hybrid search., A core node should outrank an archival node with the same base score., Boosts should not override a large relevance gap. RRF base scores are small…, Build a minimal node dict with scoring-relevant fields., Going from 0→5 accesses should give a larger boost than 15→20. (+16 more)

### Community 173 - "_linear_rescale"
Cohesion: 0.14
Nodes (11): _linear_rescale(), blend_alpha=1 means only CE matters., Candidate without 'score' key should default to 0.0., Rescale raw CE score to [0, 1] using clamped linear interpolation., Verify the linear-rescale blend formula: α * linear_rescale(ce) + (1-α) * emb., High CE score should push blended above embedding score., Very negative CE should suppress the blended score proportionally., CE=0 → rescale≈0.667, blended = 0.6*0.667 + 0.4*emb. (+3 more)

### Community 174 - "test_parser.py"
Cohesion: 0.14
Nodes (17): Tests for agent JSONL transcript normalization., A transcript whose RAW bytes dwarf its CLEANED conversation. Each turn carries…, The regression Amendment 3 exists to kill: tool-heavy turns must BATCH. Each…, A multi-turn slice's committed conversation stays within the budget — break…, The commit-site asymmetry: at the terminal-assistant site the budget check runs…, The progress guard: a lone turn bigger than the budget can't be shrunk, so it…, Tiny conversation, enormous raw span: the content budget is nowhere near full,…, A lone turn whose raw span exceeds the ceiling is committed anyway. Without… (+9 more)

### Community 175 - "forceLayout.ts"
Cohesion: 0.13
Nodes (6): createForceLayout(), start(), FA2Worker, ForceLayout, ForceLayoutOptions, STATIC_LAYOUT

### Community 176 - "permissions"
Cohesion: 0.12
Nodes (16): description, identifier, core:window:allow-close, core:window:allow-minimize, core:window:allow-start-dragging, core:window:allow-toggle-maximize, permissions, $schema (+8 more)

### Community 177 - "graph"
Cohesion: 0.12
Nodes (16): description, identifier, core:window:allow-close, core:window:allow-minimize, core:window:allow-start-dragging, core:window:allow-toggle-maximize, local, permissions (+8 more)

### Community 178 - "Investigação — o loop de rewind de cursor do #154 (2026-07-30)"
Cohesion: 0.09
Nodes (21): 10. Reprodução mínima, 1. Fontes consultadas (inventário exato), 2. O que o log de produção mostra, 3. Causa raiz, 4.1 Separar fila de inferência — refuta "trocar para llama.cpp", 4.2 Reproduzir o loop no nível do parser (sem LLM, sem engine), 4.3 Reproduzir end-to-end e testar cada branch — `tick_sim.py`, 4. Como os testes foram feitos (+13 more)

### Community 179 - "spool_proto.py"
Cohesion: 0.26
Nodes (19): run_drain(), claim(), enqueue_boundary_in_name(), enqueue_overwrite(), fresh_root(), key_for(), Path, _racer() (+11 more)

### Community 180 - "claude_cli_adapter.py"
Cohesion: 0.15
Nodes (15): _capture_pgid(), _cleanup_persisted_stub(), _kill_group_or_proc(), Claude CLI LLM adapter — headless `claude -p` via subscription auth (no paid…, HIGH-2/HIGH-1 (council-pr, Codex): signal a child's WHOLE process group by its…, SIGTERM the child's process group (stored pgid); fall back to per-PID…, SIGKILL the child's process group (stored pgid); fall back to per-PID kill()., Best-effort: delete the child's own transcript stub. Even with --no-session-… (+7 more)

### Community 181 - "MaintenanceManager"
Cohesion: 0.19
Nodes (9): MaintenanceJob, MaintenanceManager, Any, Exception, In-memory state for a single maintenance run., Run maintenance phases in background threads with single-flight semantics., Start phase 1 if needed, or return the existing job state., Start phase 2 for the current prepared job. (+1 more)

### Community 182 - "VectorStore"
Cohesion: 0.09
Nodes (26): Any, ndarray, Serialize a numpy float32 vector to bytes for sqlite-vec., sqlite-vec backed vector storage., Insert or update a vector for a node. The DELETE + INSERT pair runs inside a…, Batch insert/update vectors in a single transaction., Find nearest neighbors. Returns results with cosine similarity scores., Retrieve the stored embedding for a node, or None if not found. (+18 more)

### Community 183 - "match synthetic pattern"
Cohesion: 0.20
Nodes (5): match_synthetic_pattern(), The source of the pattern that matched, or None when the prompt is human.…, Which pattern fired — the signal rot detection needs (#143)., The empty regex matches everything and returns "" — falsy but REAL. Callers…, TestMatchSyntheticPattern

### Community 185 - "patch"
Cohesion: 0.04
Nodes (39): patch, _StopServerResult, _claude_code_plugin_provides_hooks(), configure_claude_hooks(), generate_server_wrapper(), Generate daemon wrapper with explicit, scoped API-key inheritance., True when a user-scoped ormah plugin is enabled AND actually installed. Claude…, Write Claude Code hook config to global settings using absolute paths. (+31 more)

### Community 186 - "test_setup.py"
Cohesion: 0.05
Nodes (23): Remove ormah whisper hooks from ~/.claude/settings.json., Remove the ormah instructions block from ~/.pi/agent/AGENTS.md., _remove_claude_hooks(), _remove_pi_md_block(), Path, Tests for ormah setup and server manager., Verify that run_uninstall deletes the actual memory directory regardless of…, Helper: run uninstall with a faked settings.memory_dir. (+15 more)

### Community 187 - "test_consolidator.py"
Cohesion: 0.11
Nodes (9): Tests for the memory consolidation background job., An empty/blank summary is a no-op that must still record the signature., Invalid JSON is now treated as transient (mirrors raw is None): retry next run,…, The result-fallback recovers JSON shape but not the schema's enum constraint —…, The skip table is created by init_schema()'s executescript(schema.sql), which…, test_consolidation_settings_defaults(), test_consolidation_settings_env_override(), test_inverted_cluster_bounds_returns_empty_and_warns() (+1 more)

### Community 188 - "test_migrations.py"
Cohesion: 0.33
Nodes (15): _count_conflict_checked(), _count_duplicate_checked(), _create_node(), conflict_checked appears on a standard engine fixture (schema.sql runs on every…, _seed_conflict_checked(), _seed_duplicate_checked(), test_conflict_checked_table_exists(), test_delete_node_invalidates_conflict_checked() (+7 more)

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

### Community 195 - "TestWhisperDebugMode"
Cohesion: 0.23
Nodes (6): _make_node(), mock_graph(), fixture, Tests for _return_debug mode on build_whisper_context., Nodes that don't clear the injection gate should not appear in injected_ids., TestWhisperDebugMode

### Community 196 - "TestWhisperTopicShift"
Cohesion: 0.11
Nodes (10): Topic-shift detection: skip injection when prompt is on the same topic., High similarity to recent prompts → skip whisper., Low similarity to recent prompts → proceed with whisper., Underspecified follow-up prompts should still search even on same topic., Empty recent_prompts (cold start) → always inject., None recent_prompts (cold start) → always inject., topic_shift_enabled=False → never skip, even if same topic., If encoder raises, should fall through to normal whisper. (+2 more)

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

### Community 203 - "PromptClassifier"
Cohesion: 0.18
Nodes (8): PromptClassifier, Embedding-based intent classifier for whisper-inject prompts., Classify prompt intent using cosine similarity to archetype embeddings. Lazy-…, Classify *prompt* and return an intent with search-param overrides., Tests for the embedding-based prompt intent classifier., An encoder that returns zero vectors should not crash., TestContinuationIntent, TestLazyInit

### Community 204 - "safe_error_message"
Cohesion: 0.21
Nodes (10): Guarded scheduler adapters for shared cloud protection operations., Run one scheduled backup, swallowing every exception at the scheduler boundary., Run weekly verification, swallowing every exception at the scheduler boundary., run_cloud_backup(), run_restore_verification(), Return a useful error without returning or logging credential-bearing material., safe_error_message(), test_persisted_error_keeps_nonsecret_path_for_cli_diagnostics() (+2 more)

### Community 205 - ".recall_search"
Cohesion: 0.17
Nodes (8): Search memories and return formatted results. If default_space is set and no…, Supplement results with SQL-based recent nodes when temporal filters are…, Apply multiplicative space factors to search scores and re-sort. Current…, Enrich search results with graph neighbors via spreading activation. Takes the…, Best-effort prompt vector for feedback affinity matching., Search memories and return structured results (list of dicts). Same logic as…, has_temporal_phrases(), Return True if *prompt* contains explicit temporal phrases. Unlike…

### Community 206 - "timedelta"
Cohesion: 0.22
Nodes (11): datetime, Bounded retention for high-volume whisper candidate diagnostics., Delete one bounded batch of stale, unreferenced rejected candidates. Injected…, run_whisper_log_cleanup(), _event(), Tests for normalized whisper payload retention., test_cleanup_deletes_only_stale_unreferenced_rejections(), test_cleanup_is_bounded_and_idempotent() (+3 more)

### Community 207 - "get_ormah_bin_path"
Cohesion: 0.11
Nodes (13): get_ormah_bin_path(), Find the absolute path to the ormah binary., _claude_desktop_wire(), configure_claude_code_mcp(), configure_claude_desktop(), _merge_json_file(), Read a JSON file, deep-merge updates, and write back., Register ormah MCP server in Claude Code user config. Uses ``claude mcp add``… (+5 more)

### Community 208 - "Whisper: detect rotted synthetic-prompt patterns and propose corrections — Design"
Cohesion: 0.10
Nodes (20): 1. `whisper_health` is not a table — nothing persisted can be "re-contaminated", 2. The `Proposal` Pydantic model is dead code — there is nothing to "widen", 3. Absence from `retrieval_events` does not identify a filtered prompt, 4. The `ReviewQueue` UI exists and is orphaned, 5. "Matches zero" is the wrong rot criterion, Branch strategy, Component 1 — `match_synthetic_pattern()` (`src/ormah/engine/prompt_classifier.py`), Component 2 — record the match (`whisper_decisions`) (+12 more)

### Community 209 - "run_auto_cluster"
Cohesion: 0.17
Nodes (17): Assign unassigned nodes to spaces based on their connections., run_auto_cluster(), _connect(), auto_cluster must not propagate the placeholder 'null' space (#22 council…, Startup migration re-locks legacy identity memories once (#22 council C)., The repair resets a swept identity cluster back to global + locked., Happy path still works: an unassigned node inherits a real neighbor space., A user-curated global (space_locked) keeps its None space despite project… (+9 more)

### Community 210 - "NodeFileHandler"
Cohesion: 0.19
Nodes (9): NodeFileHandler, callable, FileSystemEventHandler, Observer, Path, File system watcher for memory node changes., Watches memory/nodes/ for file changes and triggers re-indexing., Start watching the nodes directory for changes. (+1 more)

### Community 211 - "validate_llm_runtime_config"
Cohesion: 0.22
Nodes (9): Server-startup guard — deliberately NOT a pydantic validator (council C2): the…, validate_llm_runtime_config(), provider=ollama with the (Anthropic) default llm_model must fail at SERVER…, council C3: ORMAH_LLM_MODEL= (empty string) overrides the default and must be…, The Anthropic default is only wrong for ollama — claude_cli keeps working., test_validate_llm_runtime_config_accepts_explicit_ollama_model(), test_validate_llm_runtime_config_keeps_claude_cli_default(), test_validate_llm_runtime_config_rejects_empty_ollama_model() (+1 more)

### Community 212 - "Design — forgetting gate #6 must ignore non-value-bearing edges"
Cohesion: 0.17
Nodes (11): 1. One definition of value-bearing connectivity, applied to both arms **of the gate only**, 2. `evolved_from` stays protective — out of scope, on purpose, 3. Rejected ripple — the cap backstop must NOT reorder, Delivery, Design, Design — forgetting gate #6 must ignore non-value-bearing edges, Explicitly not in this change, Measured blast radius — re-measured 2026-08-13 after council review (+3 more)

### Community 213 - "constants.ts"
Cohesion: 0.15
Nodes (9): Act1Void(), Props, TITLE_CHARS, ACTS_VH, COLORS, PHYSICS, STORY_VH, TOTAL_SCROLL_VH (+1 more)

### Community 214 - "GraphCanvas.tsx"
Cohesion: 0.19
Nodes (20): GraphCanvas(), loop(), onMouseDown(), onMouseMove(), onMouseUp(), onTouchEnd(), onTouchMove(), onTouchStart() (+12 more)

### Community 215 - "pi-plugin package"
Cohesion: 0.15
Nodes (12): author, bugs, url, contributors, description, homepage, license, main (+4 more)

### Community 216 - "test mcp adapter"
Cohesion: 0.23
Nodes (8): _FakeStdioServer, asyncio, test_call_tool_connect_error_recommends_supervised_start(), test_dispatch_polls_until_phase1_batches_are_ready(), test_dispatch_polls_until_phase2_apply_completes(), test_dispatch_submit_feedback_includes_whisper_log_id(), test_dispatch_uses_extended_timeout_for_maintenance(), test_run_mcp_stdio_generates_session_id_and_runs_server()

### Community 217 - "EmbeddingAdapter"
Cohesion: 0.09
Nodes (18): EmbeddingAdapter, ndarray, Abstract base class for embedding adapters., Interface that all embedding backends must implement., Encode a single text string to a normalized vector., Encode a batch of texts to normalized vectors., Encode a search query. Override to add model-specific query prefixes., Return the dimensionality of the embedding vectors. (+10 more)

### Community 218 - "Suppressing selection with a fact, not with the cursor (ADR-0004)"
Cohesion: 0.18
Nodes (10): Considered and rejected, Decision, Invariants, Residual risks, Selection suppression, Suppressing selection with a fact, not with the cursor (ADR-0004), Tests, The mechanism is a ratchet (+2 more)

### Community 219 - "strip_temporal_phrases"
Cohesion: 0.26
Nodes (4): Remove temporal phrases from *prompt*, returning the topical residue.…, strip_temporal_phrases(), Pure temporal queries should leave some residue (stop words)., TestStripTemporalPhrases

### Community 220 - "Design: ADR-0004 Fix A — stop dead-lettering `no_safe_boundary`"
Cohesion: 0.29
Nodes (6): Context, Decision, Design: ADR-0004 Fix A — stop dead-lettering `no_safe_boundary`, Risks / non-goals, Test changes, What does not change

### Community 221 - "install_pi_md"
Cohesion: 0.21
Nodes (7): install_pi_agents(), install_pi_md(), _pi_wire(), Install ormah instructions into Pi's AGENTS.md (global or project)., Install the Ormah maintenance subagent prompt into Pi's agent directory., TestInstallPiAgents, TestInstallPiMd

### Community 222 - "format_report"
Cohesion: 0.30
Nodes (9): _collect_failures(), _fmt(), format_report(), Format whisper eval results as a human-readable table., WhisperEvalResult, _make_eval_result(), _make_result(), Tests for eval/whisper/report.py. (+1 more)

### Community 223 - "test_miner.py"
Cohesion: 0.46
Nodes (12): _decision(), _log(), _make_db(), _node(), Path, Regression tests for the whisper eval miner. Build a temp SQLite DB with the…, _run_mine(), test_deterministic_truncation_keeps_injected_node() (+4 more)

### Community 224 - "Canonical Ormah guidance block (Claude memory file)"
Cohesion: 0.19
Nodes (13): Case-design rules (labels precede runs, >=6 memories, named distractors), Whisper eval case schema (memories, prompts, expectations), Whisper golden corpus (golden/golden.jsonl, local-only), Mined provisional cases (ormah eval whisper mine), Whisper F1 baselines table (2026-07-03), Pi transcript capture (compact/shutdown to POST /ingest/conversation), Pi whisper injection (POST /agent/whisper before each prompt), Maintenance decision rules (honest none, submit all evaluated pairs) (+5 more)

### Community 225 - "TestWhisperRerankerBlendIntegration"
Cohesion: 0.14
Nodes (8): Integration tests: blended reranker through the full whisper pipeline. These…, When ALL cross-encoder scores are strongly negative (< -5), results are…, When at least one CE score is > -5, results are NOT suppressed., Custom blend_alpha should affect which results survive., Verify max_doc_chars is forwarded to reranker., Embedding min_score pre-filters; the 0.40 post-boost floor further filters.…, The reranker should change the order of results in the output., TestWhisperRerankerBlendIntegration

### Community 226 - "should_rewind"
Cohesion: 0.19
Nodes (9): Gate the leading-orphan recovery on forward progress (ADR-0003, bug #149).…, should_rewind(), ADR-0003: rewind only on NO forward progress; an orphan-with-progress is…, The #149 byte pattern: end_turn boundary, then an assistant 'API Error' record…, A genuine legacy cursor parked mid-response: orphan AND no forward progress., No-progress alone (in-flight tail) must not rewind — only orphan+no-progress…, ADR-0003 large-orphan variant: a giant orphan fragment before the first user…, ADR-0003 accepted-loss pinning (council R1, Cursor+Codex): a GENUINE legacy… (+1 more)

### Community 228 - "start_session_watcher"
Cohesion: 0.04
Nodes (76): The one spool-root path every caller must use -- never reach for /tmp. The…, A short stable hash identifying one watch root's spool. Roots must not share a…, root_key(), spool_root(), _configured_watch_roots(), _expand_watch_dir(), A live watch root: its directory, always-on handler + spool, and — only when…, Build the always-on ingest worker for every acceptance root and return the… (+68 more)

### Community 229 - "Problemas de ingestão"
Cohesion: 0.10
Nodes (20): A conta do arquivo de 3,8 MB — corrigida após medição, A pergunta da madrugada — respondida, Como cada via fatia (são diferentes), Contabilidade de volume — de onde vêm os nós (7 dias), Direção de fix proposta — extração holística por bloco (André, 2026-07-17), FINDING — timeout do `SessionEnd`, corrigido após verificação, Issues a abrir, O erro que essa comparação corrigiu (+12 more)

### Community 230 - "recall_search_structured Keyword-Only Tuning Parameters — Implementation Plan"
Cohesion: 0.40
Nodes (4): Global Constraints, Out of scope, recall_search_structured Keyword-Only Tuning Parameters — Implementation Plan, Task 1: Keyword-only tuning parameters on `recall_search_structured`

### Community 231 - "get_encoder"
Cohesion: 0.12
Nodes (16): _composite_score(), _find_merge_candidates(), Detect near-duplicate memories and create merge proposals., Jaccard similarity on lowercased word sets., Weighted composite duplicate score., Find node pairs that might be duplicates. ``delta=False`` (default — agent…, Render one candidate pair for a batched duplicate prompt (#87)., Levenshtein-ratio similarity between two titles. Returns 0.0 if either is None. (+8 more)

### Community 232 - "TestRecallFloorAndSpaceOrdering"
Cohesion: 0.30
Nodes (5): Deliberate recall: wider pool, space scores before the cut, relevance floor…, Cross-space noise penalized below the floor is dropped, not padded., A current-space match outside the old `limit` window survives the cut., A newer other-space node must NOT outrank an older current-space node., TestRecallFloorAndSpaceOrdering

### Community 233 - "Spinner"
Cohesion: 0.13
Nodes (9): Thread-safe message change., Stop spinner and print [ok] final line., Background thread: render braille animation., Animated braille spinner with elapsed time display. Usage:: with…, Spinner, In non-TTY mode, Spinner prints [..] lines instead of animating., Updating with the same message shouldn't print again., Spinner cleans up even on exception. (+1 more)

### Community 234 - "TestStopOffsetCeiling"
Cohesion: 0.20
Nodes (7): ADR-0004 Task 3: ``stop_offset`` is an ABSOLUTE hard ceiling — no turn is…, Byte offset after the first ``upto`` records, matching ``_write_jsonl``'s…, The flagged leak: ``max_conversation_chars`` commits an oversized FIRST turn…, Everything closed at or before the ceiling is committed; the first turn that…, The non-nudge lane passes ``stop_offset=None`` and must parse exactly as before., The ceiling must also clamp the Codex ``task_complete`` closure site, not only…, TestStopOffsetCeiling

### Community 235 - "test_index_embedding_retry.py"
Cohesion: 0.29
Nodes (5): _FlakyEncoder, Tests for _index_embedding bounded retry (#32)., Fails `fail_times` then succeeds, returning a fixed-dim vector., test_index_embedding_gives_up_without_raising(), test_index_embedding_retries_then_succeeds()

### Community 236 - "GraphView component (Cytoscape rendering + selection)"
Cohesion: 0.18
Nodes (11): AdminPanel (background task control via /admin/*), Edge opacity formula (max(0.2, weight or 0.5)), Graph appearance settings (localStorage ormah.graphAppearance.v1), GraphView component (Cytoscape rendering + selection), NodeDetail panel, Node sizing formula (24 + log2(access_count+1)*6), UI edge payload shape (source_id/target_id/edge_type/weight), /ui/graph data flow (load, filter client-side, node fetch, search) (+3 more)

### Community 237 - "test tool schemas"
Cohesion: 0.18
Nodes (5): get_openai_tools(), OpenAI function-calling schema adapter., Convert canonical tool schemas to OpenAI function-calling format., Canonical tool definitions shared across MCP and OpenAI adapters. TOOLS: The…, Focused tests for MCP-exposed tool schemas.

### Community 238 - "main.py"
Cohesion: 0.06
Nodes (36): BaseHTTPMiddleware, AgentMiddleware, Request, Response, Request middleware for agent_id extraction and logging., begin_cancel(), begin_lifespan(), Cancel the current epoch. Returns how many calls were in flight when it landed.… (+28 more)

### Community 239 - "relevance_quarantine.py"
Cohesion: 0.24
Nodes (10): iter_dropped(), prompt_version(), Path, quarantine_path(), Durable, append-only quarantine ledger for memories dropped by the relevance…, Path to the quarantine JSONL file, beside the store DB (settings.db_path)., First 12 hex chars of sha256 of the ingest LLM rules prompt text., Append one dropped-candidate record to the quarantine ledger. *mode* is… (+2 more)

### Community 240 - "updater.rs"
Cohesion: 0.17
Nodes (30): available_update(), available_update_store(), check(), check_desktop_update(), check_now(), concise_notes(), current_status(), desktop_update_status() (+22 more)

### Community 241 - "test_auto_linker.py"
Cohesion: 0.12
Nodes (17): Tests for LLM-based edge type classification in auto_linker., Re-writing a node's content bumps its seq to the head (crit#2 mechanism)., A direct metadata UPDATE (not via the builder) must not change seq., Council C1 regression: LLM down -> exactly one batch attempt, watermark held., Cursor regression: no pair is judged once the edge budget is spent (K=1 path)., A pair whose edge write blows up must not abort the whole run., Progress, not just survival (Codex R1, critical #2): the failing pair parks the…, A run that dies must say so in its return value — the job tracker and the admin… (+9 more)

### Community 242 - "set_cloud_backup_enabled"
Cohesion: 0.20
Nodes (11): persist_settings_delta(), Structured persistence for cloud protection settings., Persist only keys changed by a caller, serialized with every other writer., Persist and apply cloud protection without dropping unrelated settings., set_cloud_backup_enabled(), env_path(), fixture, test_account_and_protection_updates_are_serialized_without_lost_keys() (+3 more)

### Community 243 - "Session-watcher live-loss safety net — Implementation Plan"
Cohesion: 0.11
Nodes (13): Acceptance (issue #59), Branch, File map, Out of scope (YAGNI), Run tests with the working-tree interpreter, Session-watcher live-loss safety net — Implementation Plan, Tasks (do in order), Task 1: Config — reconcile interval + per-tick cap (+5 more)

### Community 244 - "test_hybrid_search_raw_cosine.py"
Cohesion: 0.33
Nodes (6): _make_hybrid(), _make_node(), Unit tests for the raw_cosine absolute-signal contract in HybridSearch. The…, A node found only via FTS (no vector hit) must carry no raw_cosine., A node with a genuine vector measurement keeps its raw_cosine., TestRawCosineContract

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

### Community 250 - "test_admin_embedding_backfill_task.py"
Cohesion: 0.20
Nodes (5): embedding_backfill must be a registered admin task in the sleep-cycle (#32)., C1/I1: a failed task yields status=degraded AND HTTP 503 (not 200)., Happy path stays a plain dict (HTTP 200) with status=completed., test_run_all_tasks_completed_returns_dict_when_all_ok(), test_run_all_tasks_degraded_returns_503_when_a_task_raises()

### Community 251 - "Design — session-watcher live-loss safety net"
Cohesion: 0.11
Nodes (18): A1. `SessionHandler.reconcile()` — single state owner, A2. `self._ingest_lock` — serialize the ingest body, A3. mtime pre-filter (perf), A4. `session_reconcile` scheduler job + supervision, A5. Functional heartbeat, A6. Plumbing, Acceptance criteria (from #59), Data flow (+10 more)

### Community 252 - "Design: Claude-CLI memory extraction (replace local gemma)"
Cohesion: 0.11
Nodes (18): 1. `ClaudeCliAdapter` (new), 2. Provider wiring, 3. Session watcher revival, Architecture (Approach A, refined), Auth / no-API gate (spike — before implementation), Branching, Components, Config surface (new) (+10 more)

### Community 253 - "recall_search_structured: keyword-only tuning parameters"
Cohesion: 0.22
Nodes (8): Contract, Decision, Out of scope, Problem, recall_search_structured: keyword-only tuning parameters, Rejected alternatives, Test plan, What the evidence changed about the framing

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
Cohesion: 0.33
Nodes (12): /ormah:setup command, /ormah:status command, /ormah:upgrade command, Ormah Claude Code plugin (manifest, hooks, MCP, commands), Plugin first-run flow (install, setup, claude-md install), ormah claude-md install (scope-matched guidance block), Claude plugin setup playbook, ormah setup --skip-client-setup (plugin-safe setup contract) (+4 more)

### Community 258 - "_node_dict"
Cohesion: 0.17
Nodes (13): _node_dict(), Convert a DB row to a plain node dict for candidate lists., mock_hybrid(), mock_hybrid_blended(), fixture, HybridSearch with blending enabled (default settings)., A result in FTS but not in vector results should score lower than one in both., Results below min_result_score should be excluded. With normalized RRF +… (+5 more)

### Community 259 - "_create_pair"
Cohesion: 0.14
Nodes (19): _apply_edge(), Record a link decision: write to auto_link_checked and optionally create an…, _create_pair(), Helper: create two similar nodes without auto-linking, return their IDs., A concurrent writer created the same edge between collection and apply.…, The winner of the race already wrote its Connection to the file. We must not…, The winner committed the DB row but crashed before saving its markdown. The…, An INSERT OR IGNORE that inserted nothing is not a creation. Counting it as one… (+11 more)

### Community 260 - "Avaliação profunda — ormah Beta (`local-main`) — 2026-07-13"
Cohesion: 0.11
Nodes (17): 10. Riscos & não verificado, 1. Sumário executivo, 2. Estado vivo do Beta (snapshot), 3. Arquitetura & código — verdictos dos hotspots, 4. Testes & operações, 5. Tecnologia — manter × trocar (pesquisa 2025-2026, com fontes), 6. Produto de memória — onde o valor vaza, 7.1 Log de produção contaminado por processos de teste — **[V mecanismo]** (+9 more)

### Community 261 - "proposals.py"
Cohesion: 0.33
Nodes (8): Proposal, ProposalStatus, ProposalType, BaseModel, Enum, str, Proposal models for merge/conflict/decay actions., ResolveProposalRequest

### Community 262 - "Setup: skip the Claude Code wiring the ormah plugin already provides — Design"
Cohesion: 0.11
Nodes (17): 1. Detection — `_claude_code_plugin_active() -> bool`, 2. `_claude_code_wire()` — the guard, 3. `_claude_code_is_wired()` — in scope by consequence, 4. Data flow, 5. Error handling, 6. Testing (TDD), Approach, Branch strategy (+9 more)

### Community 263 - "test_delete_guarded.py"
Cohesion: 0.36
Nodes (8): _archival(), _exists(), A +feedback row inserted inside the guard's txn is visible to the guard's…, The guarded delete must take L_mem BEFORE L_db, like every other decorated…, test_guard_false_aborts_deletion(), test_guard_observes_writes_in_same_transaction(), test_guard_true_deletes(), test_guarded_delete_does_not_deadlock_against_a_concurrent_writer()

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

### Community 272 - "Separate Surfaced Results from Confirmed Memory Use — Design"
Cohesion: 0.11
Nodes (17): 1. Problem, 2. What is already correct on `upstream/main`, 3. The actual defect, in four points, 4.1 Task A — subtraction, 4.2.1 Serializing the mutator, 4.2 Task B — addition, 4.3.1 The delivery contract is at-most-once, 4.3 Concurrency: the reinforcement runs outside the transaction (+9 more)

### Community 273 - "llm_errors.py"
Cohesion: 0.29
Nodes (6): LlmTimeoutError, Exception, Shared LLM adapter error types., The provider call exceeded its time budget. Distinct from a fast failure…, The maintenance path keeps its None-on-failure contract, so consolidator,…, test_llm_generate_swallows_cancel_and_timeout()

### Community 274 - "_remove_mcp_from_json"
Cohesion: 0.22
Nodes (7): _claude_desktop_unwire(), Unregister ormah MCP server from supported AI clients., Remove ormah entry from mcpServers in a JSON config file., _remove_mcp_from_json(), _remove_mcp_registration(), ~/.claude.json holds the user's whole Claude Code config, and a later change…, TestRemoveMcpFromJson

### Community 275 - "test recall concurrency"
Cohesion: 0.33
Nodes (6): Concurrency regression: recall must be safe when routes run in the threadpool.…, engine.graph.conn must resolve to the calling thread's own connection., Hammering recall_search from many threads must not raise (shared-conn race)., _remember(), test_concurrent_recall_does_not_raise(), test_graph_conn_is_per_thread()

### Community 276 - "TestMarkOutdated"
Cohesion: 0.15
Nodes (6): feedback_engine(), fixture, Tests for the mark_outdated feedback tool., Engine with a node to give feedback on., An outdated memory should get a lower score in search., TestMarkOutdated

### Community 277 - "build"
Cohesion: 0.47
Nodes (5): App, build(), Result, server_status_label(), server_toggle_label()

### Community 278 - "verify release versions"
Cohesion: 0.73
Nodes (5): main(), Path, _read_plugin_version(), _read_project_version(), verify_release_versions()

### Community 279 - "files"
Cohesion: 0.33
Nodes (6): files, ormah-pi.ts, src, pi, extensions, agents

### Community 280 - "_remove_codex_hooks"
Cohesion: 0.15
Nodes (10): _codex_unwire(), Remove Ormah agent definitions from ~/.codex/agents/., Remove ormah whisper hooks from ~/.codex/hooks.json., Remove the ormah instructions block from the active Codex AGENTS file., _remove_codex_agents(), _remove_codex_hooks(), _remove_codex_md_block(), TestRemoveCodexAgents (+2 more)

### Community 281 - "`frozen_until` Implementation Plan — Overview"
Cohesion: 0.33
Nodes (5): `frozen_until` Implementation Plan — Overview, Global Constraints, Line numbers, Setup (do this once, before Task 1), Tasks

### Community 282 - "Investigação consolidada — ingestão (2026-07-30, tarde)"
Cohesion: 0.12
Nodes (15): 1. O loop de rewind — números finais e auditoria completa, 2. Backlog real do watcher (state sweep — item aberto da §9 fechado), 3. Os 404 do Ollama — confirmado e corrigido (item aberto da §9 fechado), 4. Dedup/conflict "estagnados" — investigado: SEM perda permanente, 5. Dano do loop no store (item aberto da §9 fechado — duplicação semântica medida), 6. `min_turns` bypassado no idle — confirmado, 7. Fila do Ollama, Auditoria dos 4 call-sites de `_commit_state` (item aberto da §9 — fechado) (+7 more)

### Community 283 - "test graph focus"
Cohesion: 0.47
Nodes (5): integration, Manual real-sigma smoke check: focusing a space frames it (no blank canvas).…, _space_bbox_in_viewport(), test_space_focus_frames_the_space(), _wait_settled()

### Community 284 - "Ormah Memory Dashboard — Design"
Cohesion: 0.12
Nodes (15): Backend, Confidence metrics, Data flow, Data sources (existing), Decisions (from brainstorming), Endpoint, Engine method, Error & empty states (+7 more)

### Community 285 - "_insert_node"
Cohesion: 0.19
Nodes (8): _insert_node(), When topical results survive, identity should still be included., identity-only intent with no search results should stay silent (no graph dump)., Reranker should only affect non-identity search results. Identity nodes are…, Identity results should be suppressed when no topical results survive., Low-scoring identity results should be suppressed when no topical results…, High-scoring identity results should survive even without topical results., TestWhisperIdentityGating

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

### Community 294 - "_no_default_acceptance_roots"
Cohesion: 0.67
Nodes (3): _no_default_acceptance_roots(), fixture, D8: the real ~/.claude/projects and ~/.codex/sessions exist on the dev machine,…

### Community 295 - "Whisper: skip synthetic (machine-generated) prompts — Design"
Cohesion: 0.12
Nodes (15): 1. `<ide_opened_file>` is a wrapper, not a synthetic prompt (would cause a regression), 2. The pattern list misses the largest contributor, and it is environment-specific, 3. There is no structural signal; regex is the only route (verified, not assumed), 4. `^You are` (as proposed in the issue) is too broad for a default, Component 1 — `is_synthetic_prompt()` (`src/ormah/engine/prompt_classifier.py`), Component 2 — settings (`src/ormah/config.py`), Component 3 — the guard (`src/ormah/engine/context_builder.py`), Design (+7 more)

### Community 296 - "Embedding Delta Backfill + Continuous Reconciliation (#32) — Design"
Cohesion: 0.13
Nodes (14): Architecture, Concurrency / safety, Configuration (new settings in `config.py`), `embedding_backfill.run_embedding_backfill(engine)` (new module), Embedding Delta Backfill + Continuous Reconciliation (#32) — Design, Files, Goal, `MemoryEngine.backfill_embeddings()` (new) (+6 more)

### Community 306 - "Never advance the cursor without ingesting — design"
Cohesion: 0.13
Nodes (14): Accepted risk, Aggravating factor: the loss is unlogged, Branch placement, Change, Design, Existing tests to rewrite, Measured evidence, Never advance the cursor without ingesting — design (+6 more)

### Community 340 - "test_migration_seq.py"
Cohesion: 0.33
Nodes (5): Tests for nodes.seq column migration and backfill., Regression: a pre-seq DB must migrate without 'no such column: seq'.…, Existing nodes get a monotonic seq ordered by created ASC., test_init_schema_migrates_legacy_db_without_seq(), test_seq_column_backfilled_by_created()

### Community 341 - "ingest-deferred-tracks.md"
Cohesion: 0.18
Nodes (8): Amendment 2026-07-20 — ship in SHADOW mode, not drop-on-by-default, Amendment 2026-07-21 — lean the rollout: runtime flag, no code guard, best-effort ledger, Consequences, Considered options, The relevance gate is a provenance label the Extractor emits and code drops — no per-user calibration, Dissolved, How this ledger stays alive, Ingest — deferred tracks ledger

### Community 342 - "Auditoria do ADR-0004 — 2026-08-09"
Cohesion: 0.14
Nodes (13): 4.1 Declara como *shipped* algo que nunca foi mesclado, 4.2 A premissa está falsificada pela medição de hoje, 4.3 A cascata — porque o defeito "muda de lugar a cada council-pr", 4.4 A resposta certa já estava escrita no próprio ADR, Auditoria do ADR-0004 — 2026-08-09, O que NÃO foi verificado, Parte 1 — Decisão original (nudge, cursor no servidor, worker sempre-ligado): **CORRETA**, Parte 2 — Amendment 2026-07-22 (spool de diretório): **CORRETO, e exemplar** (+5 more)

### Community 343 - "beta-keep (150 commits) — MUST survive the Task 6 merge (not in any PR, not upstream)"
Cohesion: 0.14
Nodes (13): base-status (I2), beta-keep (150 commits) — MUST survive the Task 6 merge (not in any PR, not upstream), chore/style (4), config (2), dedup/maintenance (17), delta-manifest — Beta-only commits classification (Task 1, 2026-07-10), docs (19), index/rebuild (3) (+5 more)

### Community 344 - "test_soft_delete_tombstone.py"
Cohesion: 0.73
Nodes (5): _make(), _store(), test_list_deleted_returns_id_and_deleted_at(), test_purge_removes_tombstone(), test_soft_delete_stamps_deleted_at()

### Community 345 - "Spec — isolate `test_setup.py` from the developer's machine"
Cohesion: 0.14
Nodes (13): 1. `tests/conftest.py` — autouse fixture `_reset_settings_singleton`, 2. `tests/test_setup.py` — patch the real seam, B — the `Settings` singleton outlives test isolation (3 tests), C — `_find_binary` outflanks the mock (3 tests), Design, Evidence, Non-goals, Problem (+5 more)

### Community 346 - "LoggingHandler"
Cohesion: 0.23
Nodes (7): Lock, LoggingHandler, main(), poll_disk_truth(), Event, FileSystemEventHandler, Path

### Community 347 - "Draft comment for #209 — failure-mode analysis of the four-way duplicate policy"
Cohesion: 0.14
Nodes (13): 0. Baseline: what "clear duplicate" means operationally today, 1. Wrong auto-merge of near-duplicates (case 1 misfires), 2. Contradiction misclassified as duplicate (the case 3 / case 1 boundary), 3. Undo is asymmetric: the kept node is unrecoverable (undo fidelity, part 1), 4. Undo fidelity after downstream edits (undo fidelity, part 2), 5. Proposal invalidation races on merge/delete (agreed mechanic, not yet built), 6. Queue re-growth and starvation under "leave both alone, reconsider later" (case 2), 7. Interaction with #223's promotion path (active-only candidacy) (+5 more)

### Community 348 - "get_watermark"
Cohesion: 0.25
Nodes (12): get_watermark(), Shared seq-watermark helpers for incremental background jobs (#81). Generalizes…, Return the seq of the last fully-processed node for *key*, or 0., set_watermark(), Tests for the shared seq-watermark helpers (#81)., Mass reindex re-allocates seq; every incremental cursor must be cleared…, test_default_is_zero(), test_full_rebuild_resets_all_incremental_watermarks() (+4 more)

### Community 349 - "FakeProtectionService"
Cohesion: 0.23
Nodes (3): FakeProtectionService, _operation(), ProtectionOperation

### Community 350 - "_edges_between"
Cohesion: 0.14
Nodes (14): _edges_between(), LLM returns None -> no edge created (no heuristic fallback)., With llm_provider='none', LLM is never called and no edges are created., Return all edges between two nodes., Malformed LLM JSON → recorded as result='error' (no edge), so the node resolves., LLM classifies as supports -> edge created with type supports., LLM classifies as contradicts -> edge created with type contradicts., LLM classifies as none -> no edge created. (+6 more)

### Community 351 - "LocalAdapter"
Cohesion: 0.24
Nodes (4): LocalAdapter, ndarray, Wraps fastembed with lazy loading and caching., TestLocalAdapter

### Community 352 - "Runbook — running against the archived data directory (`ormah_old`)"
Cohesion: 0.15
Nodes (12): 1. This is read-write, not a snapshot, 2. Embedding dimension must match what wrote the index, 3. The token does not follow, 4. launchd does not see your shell, Current state (as of 2026-08-13), Four things that will bite, Open, not fixed, Rollback (+4 more)

### Community 353 - "Graph Node Size by Degree — Design"
Cohesion: 0.15
Nodes (12): Components to change, Decision: metric and formula, Goal, Graph Node Size by Degree — Design, Out of scope (backlog, separate cycles), Problem, Testing (TDD), `ui/src/graph/graphModel.test.ts` (+4 more)

### Community 354 - "Graph view: WebGL live-force migration (sigma.js)"
Cohesion: 0.15
Nodes (12): Approach decision (settled), Components (focused files, one responsibility each), Data source (unchanged), Dependencies, Goal, Graph view: WebGL live-force migration (sigma.js), Out of scope, Problem (+4 more)

### Community 355 - "Design: session-watcher catch-up off the bind path (#52)"
Cohesion: 0.15
Nodes (12): Acceptance criteria, Approach (B): observer-first + catch-up routed through the handler + shared semaphore, Components changed, Confirmed decisions, Design: session-watcher catch-up off the bind path (#52), Error handling, Fan-out bound, Problem (+4 more)

### Community 356 - ".stats"
Cohesion: 0.28
Nodes (5): Any, datetime, Return tray-facing usage counters and their window metadata., Return whisper outcome aggregates from whisper_decisions. ``whisper_decisions``…, Return the canonical stats payload for tray, CLI, UI, and diagnostics.

### Community 357 - "_serialized_memory_operation"
Cohesion: 0.10
Nodes (16): apply_identity_space_invariants(), MemoryNode, Update a memory node. Returns formatted confirmation or None., Create an edge between two nodes., Reload file, identity, and search state after a full memory restore., Identity (about_self) memories are always global: force space=None + lock so no…, Merge two nodes, keeping the better one. Returns confirmation text. When…, Rollback a merge by ID (supports prefix match). Returns confirmation. (+8 more)

### Community 358 - "Design — Graph active-first com drill-down de espaço (#22 slice 1)"
Cohesion: 0.15
Nodes (12): 1. Backend — `/ui/graph` ganha gating por tier + drill por espaço, 2. Frontend — default active + sub-view focado por espaço, 3. Interação com features do PR#17 (não regredir), 4. Componentes e fronteiras, 5. Testes (TDD), 6. Fora de escopo (explícito), 7. Acceptance criteria cobertos por esta fatia, 8. Ajustes pós-council (2026-06-29) (+4 more)

### Community 359 - "Design"
Cohesion: 0.15
Nodes (12): Content fingerprint, Data migration, Design, Evidence (live store, 2026-07-14), Flow, Out of scope, Preserve `seq` when only connections change (#126), Problem (+4 more)

### Community 360 - "Design"
Cohesion: 0.15
Nodes (12): Config, Decisions (made with André, 2026-07-15), Delta-selection for duplicate_merger + conflict_detector (upstream #81), Design, Migration, New module: `src/ormah/background/watermark.py`, Problem, Risks / out of scope (+4 more)

### Community 361 - "index_updater lock-order inversion — design"
Cohesion: 0.15
Nodes (12): Behavioural note, Delivery, Design, Evidence, Incidental benefit, index_updater lock-order inversion — design, Out of scope, Problem (+4 more)

### Community 362 - "ADR-0004 — repairing the two defects that break H1 in the ingest spool"
Cohesion: 0.15
Nodes (12): ADR-0004 — repairing the two defects that break H1 in the ingest spool, Constraints discovered before designing, Decisions, Defect 1 — the backoff cap guards the product, not the arithmetic, Defect 2 — a deleted transcript is classed as an external failure, Not in scope, Problem, Risks (+4 more)

### Community 363 - "_claude_code_is_wired"
Cohesion: 0.32
Nodes (5): _claude_code_is_wired(), Regression: the hooks branch read entry.get("command") off the matcher dict, so…, The plugin provides the hooks and MCP server; without this the UI would report…, Nothing would actually fire — reporting 'wired' would be a lie., TestClaudeCodeIsWired

### Community 364 - "install_claude_md"
Cohesion: 0.29
Nodes (3): install_claude_md(), Install ormah instructions into a Claude Code CLAUDE.md file., TestInstallClaudeMd

### Community 365 - "_run_fusion"
Cohesion: 0.17
Nodes (12): Run search with controlled FTS and vector outputs., A result with strong semantic match should outrank one with only keyword match., A result strong in both FTS and vector should outrank single-source results., Vector results below similarity_threshold should not contribute to scoring., Search should use get_nodes_batch instead of individual get_node calls., High-similarity vector result should score significantly higher than low-…, _run_fusion(), test_batch_node_fetch_used() (+4 more)

### Community 366 - "Investigação — pipeline de whisper — 2026-07-15"
Cohesion: 0.17
Nodes (11): Como funciona (pipeline), DEVE (defeitos e desperdício verificados), Investigação — pipeline de whisper — 2026-07-15, Números medidos (banco vivo, 30 dias, 2026-07-15), O que está bom (não mexer), O que é, PODE (custo/manutenção), PRECISA (confiabilidade/observabilidade) (+3 more)

### Community 367 - "Setup: stop clobbering pre-existing user config"
Cohesion: 0.17
Nodes (11): 1. `_is_ormah_hook` — single source of truth (existing), 2. `_merge_hooks(existing_hooks: dict, ormah_hooks: dict) -> dict` (new), 3. `configure_claude_hooks` / `configure_codex_hooks` (changed), 4. `_write_env_file(env: dict[str, str])` (changed; signature unchanged), Design, Goals, Non-goals, Problem (+3 more)

### Community 368 - "LLM Cancellation Redesign — Single Global Epoch"
Cohesion: 0.17
Nodes (11): Acceptance criteria, Consequences, Known risks, LLM Cancellation Redesign — Single Global Epoch, Out of scope, Ownership: who cancels, and when, The adapter becomes a pure epoch consumer, The design (+3 more)

### Community 369 - "OllamaEmbeddingAdapter"
Cohesion: 0.25
Nodes (4): OllamaEmbeddingAdapter, ndarray, Produces embeddings via a local Ollama instance., TestOllamaAdapter

### Community 370 - ".startup"
Cohesion: 0.17
Nodes (6): Initialize on server start: rebuild index if empty, ensure self node., Seed FSRS stability from access_count on first run, updating both DB and…, Avoid firing agent-backed maintenance immediately on fresh installs., One-time migration: fix identity node tiers and edges. Phase 1…, One-time: lock the identity cluster's space as global so auto_cluster never…, Load the embedding model now so the first request doesn't stall. On a fresh…

### Community 371 - "._embed_node_rows"
Cohesion: 0.20
Nodes (5): Full rebuild of the index from markdown files, including embeddings., Embed the given node rows into the vector store. Encode and upsert are…, Re-embed all nodes in the index., Embeddable nodes with no row in the vector store (the honest gap)., Reconcile the vector store. Idempotent; safe to run repeatedly. Two modes: -…

### Community 372 - "Handoff — ADR-0004 slice 3 (`no_safe_boundary`): plano revisado 5×, nada implementado (2026-07-28)"
Cohesion: 0.18
Nodes (10): Armadilhas que vão te morder, As 5 rodadas — o que cada uma matou, Bug ATIVO no Beta, descoberto aqui — anterior a esta branch, Diagnóstico — medido, não estimado, Estado da revisão — leia antes de assumir que está aprovado, Handoff — ADR-0004 slice 3 (`no_safe_boundary`): plano revisado 5×, nada implementado (2026-07-28), O documento que importa, O que foi decidido (não re-litigar) (+2 more)

### Community 373 - "ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the queue"
Cohesion: 0.18
Nodes (10): ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the queue, Beta Rollout (operator steps, after merge to local-main), Council amendments that survive the rewrite, Council round on the rewrite (2026-07-22, R12) — all 11 findings accepted, Global Constraints, Key Anchors (verified 2026-07-21 on local-main @ 66405d9), ⚠️ Rewritten 2026-07-22 — read the ADR amendment first, Slicing (decided 2026-07-21 after 8 council rounds) (+2 more)

### Community 374 - "Design: Session Watcher Cursor Safety"
Cohesion: 0.18
Nodes (10): Affected files, Bug 1 — Mid-turn race, Bug 2 — Session tail loss, Design, Design: Session Watcher Cursor Safety, Fix 1 — `safe_end_offset` in `parse_transcript`, Fix 2 — Idle/mtime flush in `_ingest_session`, New tests (+2 more)

### Community 375 - "Whisper-health metric — design"
Cohesion: 0.18
Nodes (10): Approach, Components, `compute_whisper_health(conn, now) -> dict` (new), `engine.stats()` (edit), Key design decision — coverage uses `DISTINCT whisper_log_id`, Out of scope, Problem, Testing (TDD) (+2 more)

### Community 376 - "ormah-backup-ux-check.sh"
Cohesion: 0.27
Nodes (10): checkpoint(), cleanup(), fail(), ORMAH_BACKUP_DIR, ORMAH_MEMORY_DIR, ORMAH_PORT, pass(), PATH (+2 more)

### Community 377 - "TestSpaceScoring"
Cohesion: 0.31
Nodes (5): Tests for score-based space prioritization in MemoryEngine., Same-space results score higher than otherwise-identical cross-project results., A high-relevance cross-project result still beats a weak current-project result., Global (space=None) results get the global boost factor., TestSpaceScoring

### Community 378 - "fit.test.ts"
Cohesion: 0.20
Nodes (7): FIT_PADDING_RATIO, fitToNodes(), MIN_FIT_RATIO, NOTE: the relative-ratio step assumes camera.angle === 0 (no rotation). This…, FakeOpts, Framed, Pt

### Community 379 - "UpdateBanner.tsx"
Cohesion: 0.31
Nodes (7): UpdateBanner(), DesktopUpdatePhase, desktopUpdateProgress(), desktopUpdater, DesktopUpdateStatus, isDesktopApp(), native()

### Community 380 - "ADR-0004 Slice 2 — Bounded shutdown: cancel in-flight extractions"
Cohesion: 0.20
Nodes (9): ADR-0004 Slice 2 — Bounded shutdown: cancel in-flight extractions, Council round on the refresh (2026-07-23, R1 — cursor + codex, all findings accepted), Design decisions carried from the council review (all findings accepted), Global Constraints, Key Anchors (RE-VERIFIED 2026-07-23 on merged local-main, post-`7cd15cb`), Prerequisite, ⚠️ Refreshed 2026-07-23 — re-verified against the MERGED slice 1, Rollout note (+1 more)

### Community 381 - "Galaxy graph: tractable clustered layout at scale"
Cohesion: 0.20
Nodes (9): Approach (chosen: C — deterministic macro + local micro-force), Galaxy graph: tractable clustered layout at scale, Interaction with the two already-verified fixes, Mode `clusterBySpace` OFF, Mode `clusterBySpace` ON (default), Out of scope, Problem, Risk to validate during implementation (+1 more)

### Community 382 - "Graph Per-Space Cohesion (#22 slice B) — Design"
Cohesion: 0.20
Nodes (9): Ceiling (ponytail), Decisions (locked in brainstorming), Graph Per-Space Cohesion (#22 slice B) — Design, Helper (testability), Module: `ui/src/graph/clusterLayout.ts`, Out of scope, Problem, Testing (TDD, pure functions) (+1 more)

### Community 383 - "Verificação independente — problemas-de-ingestao.md"
Cohesion: 0.20
Nodes (9): Achados NOVOS (não estavam no doc), Issues a abrir — ajustes sobre a lista do doc, N1 — o maior motor de duplicação é outro: o loop `recovering legacy mid-response cursor`, N2 — o design síncrono é insustentável por aritmética, não por azar, N3 — menores, O que isso muda na ordem recomendada do doc, Registro de confiança desta verificação, Veredito por afirmação do doc (+1 more)

### Community 384 - "Fork & contribution workflow (Ormah)"
Cohesion: 0.20
Nodes (9): Anti-patterns (these are the "merging becomes a mess" pain), Fork & contribution workflow (Ormah), Golden rules, Mental model (the one thing that prevents every problem), Recipe A — contribute a change upstream, Recipe B — also run the change in your Beta right now, Recipe C — sync down (upstream advanced / your PR landed), Recipe D — branch hygiene (prune) (+1 more)

### Community 385 - "Amendment 2026-08-11 — nothing shipped, the P1 gate never enforced, and move 2 loses its gate"
Cohesion: 0.22
Nodes (9): Amendment 2026-08-11 — nothing shipped, the P1 gate never enforced, and move 2 loses its gate, Consequences, Considered options, Merge stays human-curated: bound the review queue and honor rejections, not autonomous merge, Move 2 is ungated, Residual risk, Still true, verified, Unchanged (+1 more)

### Community 386 - "Proposal — Memory lifecycle: clock calibration, cold layer, and Deep Recall"
Cohesion: 0.22
Nodes (8): 1. Problem, 2. Current lifecycle, 3. Proposed lifecycle, 4. Design points, 5. Delivery plan (small PRs, replacing the current branch shape), 6. Open questions, 7. Evidence behind v3, Proposal — Memory lifecycle: clock calibration, cold layer, and Deep Recall

### Community 387 - "Beta ↔ Upstream Sync — Implementation Plan (overview)"
Cohesion: 0.22
Nodes (8): Beta ↔ Upstream Sync — Implementation Plan (overview), Clone / remote map (do not confuse), Council review (2026-07-10, cursor+codex, R1) — 8 fixes folded in, Decisions (André, 2026-07-10), Global rules (apply to every task), Known baseline facts (verified 2026-07-10 unless noted), Risks, Tasks

### Community 388 - "Delta-selection for dedup/conflict (#81) — Implementation Plan Overview"
Cohesion: 0.22
Nodes (8): Delta-selection for dedup/conflict (#81) — Implementation Plan Overview, Files, Known limitations (documented in the PR body, out of scope), Load-bearing invariants (every task must preserve), Pre-flight (once, before Task 1), Reconciliation note (#95 / judge_pairs), Tasks, Verification (after Task 5)

### Community 389 - ".search"
Cohesion: 0.29
Nodes (7): _is_question_query(), Any, Detect whether a query is a natural language question., Hybrid search with Reciprocal Rank Fusion. ``query_vec`` may be supplied by a…, parametrize, test_question_detection_negative(), test_question_detection_positive()

### Community 390 - "Ingest batches are sized to a recall sweet spot, not the context window; delta ordered first"
Cohesion: 0.25
Nodes (8): Amendment (2026-07-17): the sweet spot is a model-agnostic conservative default, not a per-model window, Amendment 2 (2026-07-17): the extraction chunk must be ≥ the flush batch — `chunk_chars ≥ flush_bytes`, Amendment 3 (2026-07-25): the budget is measured on the wrong quantity — bytes of transcript, not conversation the Extractor sees, Consequences, Consequences and sequencing, Considered options, Decision, Ingest batches are sized to a recall sweet spot, not the context window; delta ordered first

### Community 391 - "Amendment 2026-08-09 — the 2026-07-28 force-close REMEDY is retracted; its DIAGNOSIS is confirmed and still open"
Cohesion: 0.25
Nodes (8): Amendment 2026-08-09 — the 2026-07-28 force-close REMEDY is retracted; its DIAGNOSIS is confirmed and still open, It was never shipped, Newly measured, and not previously known: recoverability expires, Status of the branch, The loss is real — but it is not the dead-letter, and it is not a tail, The premise: re-measured 2026-08-09, What replaces it, Why the design did not converge — the cascade

### Community 392 - "Amendment 2026-08-13 — Fix A ships: the `no_safe_boundary` dead-letter is retired, not just re-admitted"
Cohesion: 0.25
Nodes (8): Amendment 2026-08-13 — Fix A ships: the `no_safe_boundary` dead-letter is retired, not just re-admitted, Operational signal, corrected before merge, Recovery of the lost content — retired by decision, not by repair, Still open, The 2026-08-12 census, re-measured 2026-08-13, The `PARKED` short-circuit: cleared by two reviews, and wrong — `468d38e`, What Fix A closes, What shipped, and why it is not the design's original shape

### Community 393 - "ADR-0004 Async Ingest (Nudge + Server Cursor) — Implementation Plan"
Cohesion: 0.25
Nodes (7): ADR-0004 Async Ingest (Nudge + Server Cursor) — Implementation Plan, Beta Rollout (after merge to local-main — operator steps, not code), Council amendments (R1-R5, 2026-07-21) — all findings accepted, Delivery: **Beta-first**, upstream contribution deferred (council R5, decisive), Global Constraints, Key Anchors (verified 2026-07-21 on local-main @ 66405d9), Task Map (execution order 1 → 2 → 3 → 4 → 5 → 7 → 6)

### Community 394 - "ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the cursor"
Cohesion: 0.25
Nodes (7): ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the cursor, Beta Rollout (operator steps, after merge to local-main), Council amendments carried into this slice (R1-R9, all findings accepted), Global Constraints, Key Anchors (verified 2026-07-21 on local-main @ 66405d9), Slicing (decided 2026-07-21 after 8 council rounds), Task Map

### Community 395 - "Task 6: Rewrite GraphView as a sigma orchestrator"
Cohesion: 0.25
Nodes (7): 6.1 — Mount sigma + build graph + run layout, 6.2 — Hover highlight + selection, 6.3 — Imperative ref API on sigma, 6.4 — Full legend reuse + FOCUS semantics (Council M2 + A1), 6.5 — Node drag (reheat) + hover tooltip, 6.6 — `focusNodeId` prop + zoom controls (Council M1, M3), Task 6: Rewrite GraphView as a sigma orchestrator

### Community 396 - "Graph Per-Space Cohesion (#22 slice B) — Implementation Plan"
Cohesion: 0.25
Nodes (7): File structure (decomposition), Graph Per-Space Cohesion (#22 slice B) — Implementation Plan, Key facts the engineer must not rediscover, Out of scope, Run commands (this repo), Task order, Why the size gate (council R1, accepted)

### Community 397 - "Plan delta — r-spade alignment (issue #73)"
Cohesion: 0.25
Nodes (7): Achado que reenquadra a Task 04, Duas decisões que mudam a premissa, Mudanças por task, Pendências antes do PR, Plan delta — r-spade alignment (issue #73), Respostas de design postadas (contexto, não exigem código agora), Seam genérico exigido pelo owner

### Community 398 - "Setup: skip the Claude Code wiring the ormah plugin already provides — Implementation Plan"
Cohesion: 0.25
Nodes (7): Finishing — after Task 4, Global Constraints, Interfaces introduced, Known limitation (deliberate, tested), Setup — before Task 0, Setup: skip the Claude Code wiring the ormah plugin already provides — Implementation Plan, Task order and why

### Community 399 - "Synthetic-Pattern Rot Detection — Implementation Plan (overview)"
Cohesion: 0.25
Nodes (7): Deviation from the spec (deliberate, verified), File Structure, Global Constraints, Out of scope, Synthetic-Pattern Rot Detection — Implementation Plan (overview), Tasks, Verification (after task 4 — not "tests pass")

### Community 400 - "ADR-0004 Slice 3 — Extraction timeout: health-gated, shrink-first quarantine"
Cohesion: 0.25
Nodes (7): ADR-0004 Slice 3 — Extraction timeout: health-gated, shrink-first quarantine, ⛔ BLOCKED: this slice needs its own ADR first, Design (survivor of council rounds R1-R8 — all findings accepted), Global Constraints, Key Anchors (verified 2026-07-21 on local-main @ 66405d9), Prerequisites, Task Map

### Community 401 - "Cursor Rewind Loop Fix (#154) — Implementation Plan (Overview)"
Cohesion: 0.25
Nodes (7): Cursor Rewind Loop Fix (#154) — Implementation Plan (Overview), Deferred (tracked, NOT in this plan), Final Verification (after all tasks, before /council-pr), Global Constraints, Revision log, Rollout (post-merge, needs explicit authorization — touches the live Beta), Tasks

### Community 402 - "Frozen-Prefix Cursor Loss — Overview"
Cohesion: 0.25
Nodes (7): Frozen-Prefix Cursor Loss — Overview, Global Constraints, Interfaces that cross task boundaries, Setup — run once, before Task 1, Tasks, The defect in one paragraph, Why deletion, not a park

### Community 403 - "Mapa do backlog upstream — local-main vs r-spade/ormah"
Cohesion: 0.25
Nodes (7): Clusters temáticos (por commit scope / issue), Contribuibilidade, CORREÇÃO (2026-07-23) — o backlog JÁ está contribuído, Mapa do backlog upstream — local-main vs r-spade/ormah, Números, Ordem sugerida de fatias (se a decisão for contribuir), Áreas de código (arquivos)

### Community 404 - "_reciprocal_rank_fusion"
Cohesion: 0.25
Nodes (8): Fuse multiple ranked lists using weighted Reciprocal Rank Fusion. Each list…, _reciprocal_rank_fusion(), A node in both lists should score higher than one in only one list., Higher weight should give proportionally higher contribution., test_rrf_empty_lists(), test_rrf_overlap_accumulates(), test_rrf_single_list(), test_rrf_weights_scale_contribution()

### Community 405 - "Amendment 2026-08-13 — Fix B ships: suppression is a fact about the file, not a cursor advance"
Cohesion: 0.29
Nodes (7): Amendment 2026-08-13 — Fix B ships: suppression is a fact about the file, not a cursor advance, Correction to the 2026-08-11 amendment, Not shipped, deliberately: `reconcile`'s `>=`, Still open, Verification in production — confirmed by a second reading, What shipped, Withdrawn: the errata this amendment was going to carry

### Community 406 - "Embedding Delta Backfill (#32) Implementation Plan — Overview"
Cohesion: 0.29
Nodes (6): Conventions for every task, Core concepts (council R2 baked in — no quarantine), Embedding Delta Backfill (#32) Implementation Plan — Overview, File map, Key design points, Task order & dependencies

### Community 407 - "Claude-CLI memory extraction — Implementation Plan (overview)"
Cohesion: 0.29
Nodes (6): Branch, Claude-CLI memory extraction — Implementation Plan (overview), Cross-cutting invariants, File map, Non-goals (locked in spec), Task sequence

### Community 408 - "ADR-0004 Spool H1 Repair — Overview"
Cohesion: 0.29
Nodes (6): ADR-0004 Spool H1 Repair — Overview, After the plan, Global Constraints, Shell prefix used by every command in every task, Task 0: Confirm the harness runs against the worktree (do this first, always), Tasks

### Community 409 - "_remove_fastembed_cache"
Cohesion: 0.39
Nodes (3): Delete the fastembed model cache entries that ormah downloaded., _remove_fastembed_cache(), TestRemoveFastembedCache

### Community 410 - "TestWhisperSignal"
Cohesion: 0.29
Nodes (4): No signal when claude_maintenance_enabled=False., No signal when maintenance was run within the interval., Signal appears when no maintenance has ever been run., TestWhisperSignal

### Community 411 - "Amendment 2026-08-11 — H1's "retry forever" has a hard stop at attempt 1025, and a deleted transcript never reaches the dead-letter"
Cohesion: 0.33
Nodes (6): A deleted transcript is classed as an external failure, against the contract, Amendment 2026-08-11 — H1's "retry forever" has a hard stop at attempt 1025, and a deleted transcript never reaches the dead-letter, How it ended, and what that cost, The backoff cap is applied after the exponentiation, so it never guards the arithmetic, The stranded job is re-admitted with no backoff, which is why it repeats, What this does not change

### Community 412 - "Amendment 2026-07-28 — slice 3: the frozen tail is force-closed automatically, behind an anti-rewind checkpoint"
Cohesion: 0.33
Nodes (6): Accepted cost, Amendment 2026-07-28 — slice 3: the frozen tail is force-closed automatically, behind an anti-rewind checkpoint, Known gap, deliberately not closed here, The policy as shipped, What the measurement changed, Why pure force-close is wrong (the council rejected it; do not reintroduce it)

### Community 413 - "Draft — reply to r-spade on PR #31 — SUPERSEDED 2026-07-14"
Cohesion: 0.33
Nodes (5): Branch shape, Draft — reply to r-spade on PR #31 — SUPERSEDED 2026-07-14, One confession about where this PR came from, The sequence I'd propose, What re-examining the archival tier turned up

### Community 414 - "Problema 1 — o julgamento de relevância é um prompt, não um gate"
Cohesion: 0.33
Nodes (6): A evidência de que não funciona, Como funciona hoje, De onde isso veio: o extrator memoriza o que passa pela tela, Onde a hipótese "é a mesma coisa N vezes" vale e onde não vale, Por que isso é estrutural, não um bug de prompt, Problema 1 — o julgamento de relevância é um prompt, não um gate

### Community 415 - "Graph view WebGL live-force migration — Implementation Plan (overview)"
Cohesion: 0.33
Nodes (5): Conventions, File structure, Graph view WebGL live-force migration — Implementation Plan (overview), Out of scope (from spec), Tasks (in order)

### Community 416 - "Graph active-first com drill-down de espaço — Implementation Plan (#22 slice 1)"
Cohesion: 0.33
Nodes (5): Ajustes do council (2026-06-29), Graph active-first com drill-down de espaço — Implementation Plan (#22 slice 1), Notas operacionais, Out of scope, Tasks (executar em ordem)

### Community 417 - "Task 6 — Fixes do council v2 (C1/C2/C3) + cobertura"
Cohesion: 0.33
Nodes (5): 6a. Extrair `buildDimmed` puro e scope-aware (C1 + C2 + cobertura CX3), 6b. `loadGraph` no-space filter + tratamento de erro (C1 overview + C3), 6c. Correções de contagem no plano (C4), Task 6 — Fixes do council v2 (C1/C2/C3) + cobertura, Verificação adicional (somar à Task 5)

### Community 418 - "SPIKE-FINDINGS — Task 01 (GATE)"
Cohesion: 0.33
Nodes (5): Base-divergence note (origin/main vs the plan's local-main assumptions), Deferred, Fixture, Gate results, SPIKE-FINDINGS — Task 01 (GATE)

### Community 419 - "ADR-0003 — Orphan Progress Guard: Implementation Plan (Overview)"
Cohesion: 0.33
Nodes (5): ADR-0003 — Orphan Progress Guard: Implementation Plan (Overview), Global constraints, Interfaces (shared across tasks), Tasks, Verified parser facts the tests rely on

### Community 420 - "index_updater Lock-Order Inversion — Implementation Plan"
Cohesion: 0.33
Nodes (5): Global Constraints, index_updater Lock-Order Inversion — Implementation Plan, Standing warnings, Tasks, The defect in one picture

### Community 421 - "Separate Surfaced Results from Confirmed Memory Use — Implementation Plan"
Cohesion: 0.33
Nodes (5): Global Constraints, Out of scope, Separate Surfaced Results from Confirmed Memory Use — Implementation Plan, Setup — run once, before Task 1, Task Order

### Community 422 - "Setup Test Env Isolation — Overview"
Cohesion: 0.33
Nodes (5): Global Constraints, Non-goals, Root causes and why each fix is shaped that way, Setup Test Env Isolation — Overview, Tasks

### Community 424 - "routes_stats.py"
Cohesion: 0.33
Nodes (5): get, Request, Canonical stats API route., Canonical stats payload for tray, CLI, UI, and diagnostics., stats()

### Community 425 - "._write_audit_log"
Cohesion: 0.33
Nodes (3): Delete a memory node from disk and index. Returns confirmation or None., Mark a memory as outdated: set valid_until to now, optionally append reason., Insert an entry into the audit_log table.

### Community 426 - ".test_ce_reorders_results"
Cohesion: 0.33
Nodes (4): Verify results are sorted by blended score descending., High CE on a lower-embedding result should promote it., Same CE score → sort by embedding contribution (higher emb first)., TestSorting

### Community 427 - "TestSessionBufferRoute"
Cohesion: 0.33
Nodes (4): Tests for the per-session prompt buffer in the whisper route., Buffer should accumulate prompts per session., Different session IDs should have independent buffers., TestSessionBufferRoute

### Community 428 - "Problema 3 — o churn de `seq` (refutado como causa do backlog)"
Cohesion: 0.40
Nodes (5): A cadeia de código (confirmada, elo a elo), Conclusão, Estado atual (12:35 -03, Agente 5), Por que a cadeia não explica o backlog, Problema 3 — o churn de `seq` (refutado como causa do backlog)

### Community 429 - "Task 3 — Pure helpers: `buildSpaceLegend` + `scopeLabel`"
Cohesion: 0.40
Nodes (4): 3a. `buildSpaceLegend`, 3b. `scopeLabel`, 3c. `createRequestGuard` (F2 — race de reload), Task 3 — Pure helpers: `buildSpaceLegend` + `scopeLabel`

### Community 430 - "live_patterns"
Cohesion: 0.40
Nodes (5): live_patterns(), (pattern_source, origin) for every pattern the filter would apply today.…, One regex must yield one entry, or it yields two proposals (council I1)., test_live_patterns_dedups_an_operator_copy_of_a_builtin(), test_live_patterns_includes_builtins_and_operator_entries()

### Community 431 - ".test_exactly_at_threshold_passes"
Cohesion: 0.33
Nodes (4): Test the exact boundary where results pass/fail the threshold., Score exactly at min_score should be included (>=)., Score just below min_score should be excluded., TestBlendedScoreBoundary

### Community 432 - "Recovery drops an orphan fragment rather than re-ingesting the whole transcript"
Cohesion: 0.50
Nodes (3): Consequences, Considered options, Recovery drops an orphan fragment rather than re-ingesting the whole transcript

### Community 433 - "⛔ SUPERSEDED — this plan was split into three slices (2026-07-21)"
Cohesion: 0.50
Nodes (3): ⛔ SUPERSEDED — this plan was split into three slices (2026-07-21), What survived the review (carried into the slices), Why it was split

### Community 434 - "Task 4 — Wiring: `App.tsx` (estado + fetch) e `GraphView.tsx` (legenda drill + banner)"
Cohesion: 0.50
Nodes (3): 4a. `App.tsx`, 4b. `GraphView.tsx`, Task 4 — Wiring: `App.tsx` (estado + fetch) e `GraphView.tsx` (legenda drill + banner)

### Community 435 - "Task 2: Add `_claude_code_plugin_provides_hooks()`"
Cohesion: 0.50
Nodes (3): Task 2: Add `_claude_code_plugin_provides_hooks()`, The two states this predicate must AND together — **[council]**, Why user scope only — **[council]**

### Community 436 - "Task 2: Always-on Ingest worker — drains the spool; Observer becomes optional"
Cohesion: 0.50
Nodes (3): Task 2: Always-on Ingest worker — drains the spool; Observer becomes optional, Test disposition — the plan undercounted the fallout (re-plan 2026-07-23), The drain loop

### Community 437 - "test_expired_tombstone_is_purged_and_audited"
Cohesion: 0.60
Nodes (5): _backdate_tombstone(), test_expired_tombstone_is_purged_and_audited(), test_purge_skipped_when_disabled(), test_tombstone_within_window_is_kept(), _tombstone_ids()

### Community 464 - "test_full_rebuild_resets_watermark"
Cohesion: 0.50
Nodes (4): _set_watermark(), A mass reindex must not leave a stale watermark hiding the whole store., test_full_rebuild_resets_watermark(), test_watermark_roundtrip()

### Community 553 - "backup_dir"
Cohesion: 0.67
Nodes (3): backup_dir(), fixture, A minimal finished local backup: nodes/, deleted/, backup.json.

### Community 555 - "_isolate_cache"
Cohesion: 0.67
Nodes (3): _isolate_cache(), fixture, Point the whisper cache (outbox, lock, counters, legacy cursor) at a temp dir…

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
- **1244 isolated node(s):** `build-sidecar.sh script`, `ormah-desktop`, `$schema`, `identifier`, `description` (+1239 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **134 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

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
- **Why does `MemoryEngine` connect `MemoryEngine` to `test_session_watcher.py`, `test_hippocampus.py`, `NodeType`, `session_watcher.py`, `recall/cli.py`, `Settings`, `TestClient`, `test_claude_cli_adapter.py`, `seed_case`, `SessionHandler`, `conftest.py`, `test_session_watcher_flush.py`, `config.py`, `JobTracker`, `test_memory_engine.py`, `test_confirmed_use_contract.py`, `run_eval`, `._write_audit_log`, `Database`, `IndexBuilder`, `ContextBuilder`, `test_ingest_extraction.py`, `MaintenanceManager`, `VectorStore`, `FileStore`, `get_or_create_store_id`, `test_account_billing_routes.py`, `test cleanup auto ingested`, `.recall_search`, `hippocampus.py`, `timedelta`, `run_forgetting`, `get_fastembed_cache_dir`, `CreateNodeRequest`, `TestSubmitFeedbackBasic`, `test relevance runner`, `TestWhisperDecisions`, `start_session_watcher`, `start_scheduler`, `whisper/cli.py`, `_serialized_memory_operation`, `.stats`, `get_encoder`, `TierManager`, `EdgeType`, `run_whisper_eval`, `main.py`, `GraphIndex`, `HybridSearch`, `.startup`, `memory_engine.py`, `._embed_node_rows`, `TestSpaceScoring`, `seed_case`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._