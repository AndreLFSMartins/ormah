# Graph Report - ormah  (2026-08-19)

## Corpus Check
- 759 files · ~896,426 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 9893 nodes · 20661 edges · 561 communities (418 shown, 143 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2869 edges (avg confidence: 0.62)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `86a47f81`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ok
- test_session_watcher.py
- main.py
- protection.py
- product_bridge.rs
- IngestSpool
- Pi Plugin Client
- CloudProtectionService
- rerank
- memory_engine.py
- Tauri Sidecar Commands
- timedelta
- test_config.py
- test_whisper_context.py
- load_state
- Ingest is async: the client nudges, the server owns the cursor and advances on job completion
- session_watcher.py
- context_builder.py
- GraphView.tsx
- Settings
- routes_agent.py
- start_session_watcher
- test_claude_cli_adapter.py
- recovery.py
- CloudState
- routes_account.py
- SessionHandler
- run_conflict_detection
- store_lock.py
- test_session_watcher_flush.py
- NodeType
- test_eval_whisper/test_metrics.py
- test_duplicate_merger.py
- JobTracker
- llm/__init__.py
- ormah/cli.py
- Tauri Bundle Config
- test_whisper_out.py
- IndexBuilder
- test_confirmed_use_contract.py
- open_bundle
- GraphIndex
- forgetting_manager.py
- CloudCryptoError
- CLI Adapter Tests
- ._builder
- api.ts
- routes_admin.py
- run_setup
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
- local_auth.py
- test_ingest.py
- test_temporal_search.py
- run_uninstall
- ProtectionOperationKind
- test_spreading_activation.py
- TestClient
- CloudClient
- routes_protection.py
- install_autostart
- test_eval_recall/test_metrics.py
- test cleanup auto ingested
- run_auto_linker
- cli_adapter.py
- _claude_code_plugin_provides_hooks
- ConnectRequest
- test_seq_fingerprint.py
- configure_codex_mcp
- test feedback schema
- test_hybrid_search.py
- FastAPI
- RecoveryKitError
- validate_case
- run_forgetting
- llm_client.py
- get_fastembed_cache_dir
- test pair batch
- src/types.ts
- Recomendações para o Ormah como projeto open source
- TestSafeBoundary
- recall/cli.py
- SessionWatch
- restore.py
- run_setup_json
- TestSubmitFeedbackBasic
- test relevance runner
- _NeverEofProc
- 2026-08-19-hippocampus-flake-condition-waiting/00-overview.md
- run_whisper_eval
- test_mutation_stamping.py
- start_scheduler
- whisper/cli.py
- bundle.py
- test_routes.py
- desktop ui package
- TierManager
- whisper/runner.py
- parse_transcript
- test_cloud_cli.py
- get_watermark
- CreateNodeRequest
- seed_case
- setup_logging
- test_setup.py
- test_backup.py
- extract_time_params
- _make_engine_with_encoder
- PromptIntent
- PromptClassifier
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
- run_eval
- extract_json
- MemoryEngine facade
- APScheduler background scheduler
- test_account_auth_routes.py
- Design — Issue #223: reversible promotion and the seven-day initial lease
- .generate
- duplicate_merger.py
- test_cli_cloud_backup.py
- test_main_backfill_fallback.py
- Whisper pipeline (involuntary recall)
- _FakeEngine
- auto_linker edge-write hardening — Overview
- compute_affinity_boost
- test_backfill_embeddings.py
- test_scoring_signals.py
- llm_generate
- test_stats.py
- entitlements.py
- visual.ts
- _find_link_candidates
- routes_ui.py
- conftest.py
- cmd_whisper_store
- test_cli_account.py
- TestSyntheticPromptEndpoint
- Ormah Desktop (Tauri v2 app)
- TestReleaseVersionVerification
- scenario
- ORMAH  settings and .env load order
- test_audit_log.py
- Database
- compilerOptions
- Review Relevance Is Not Confirmed Use — Implementation Plan
- normalize_conflict_type
- test_llm_cancel.py
- _FakeEngine
- Review relevance is not confirmed use
- MaintenanceManager
- _insert_node
- test_protection_routes.py
- detect_space_from_cwd
- Changes
- OllamaEmbeddingAdapter
- forceLayout.ts
- permissions
- graph
- Investigação — o loop de rewind de cursor do #154 (2026-07-30)
- spool_proto.py
- _claude_code_wire
- test_cloud_settings.py
- stored_or_encoded
- match synthetic pattern
- 01-gate-the-claim.md
- patch
- test_memory_engine.py
- TestConsolidationSignatureSkip
- test_migrations.py
- Desktop release build job (macOS + Linux matrix)
- HybridSearch pipeline
- CloudProtectionService (reusable owner of backup now and res
- Force-Directed Graph Canvas (full-bleed)
- cmd_eval_whisper_run
- 02-pin-legacy-fallback.md
- _remove_claude_md_block
- _merge_hooks
- Reconciling #126 (pair-verdict invalidation) with #208 (lock-order hoist) in IndexBuilder
- TestGetMaintenanceBatches
- test graph
- ormah setup wizard
- graph
- routes_ingest.py
- MemoryEngine
- FakeProtectionService
- llm_errors.py
- test_hippocampus.py
- test_parser.py
- Whisper: detect rotted synthetic-prompt patterns and propose corrections — Design
- _remove_fastembed_cache
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
- VectorStore
- llm_cancel.py
- test_miner.py
- Canonical Ormah guidance block (Claude memory file)
- transfer.py
- should_rewind
- TestWhisperDecisions
- _monkeypatch_run_embedding_backfill
- Problemas de ingestão
- recall_search_structured Keyword-Only Tuning Parameters — Implementation Plan
- TestWhisperSignal
- TestRecallFloorAndSpaceOrdering
- _CancellableEngine
- test_candidate_discovery_failure_is_reported_not_swallowed
- test_run_stats.py
- GraphView component (Cytoscape rendering + selection)
- test tool schemas
- Spinner
- relevance_quarantine.py
- updater.rs
- test_auto_linker.py
- client.py
- Session-watcher live-loss safety net — Implementation Plan
- key_path
- Ormah Desktop App Icon (canonical 512px master)
- renderer
- Encoder factory (get encoder   get adapter)
- Ormah system map
- age encryption envelope (client-side, private identity never
- 2026-08-19-claude-cli-fixed-system-prompt/00-overview.md
- Design — session-watcher live-loss safety net
- Design: Claude-CLI memory extraction (replace local gemma)
- recall_search_structured: keyword-only tuning parameters
- hatch build
- Ormah Project Banner Image
- Canonical ormah-maintenance agent (mcp  ormah  run maintenan
- Ormah Claude Code plugin (manifest, hooks, MCP, commands)
- HybridSearch
- _create_pair
- Avaliação profunda — ormah Beta (`local-main`) — 2026-07-13
- Path
- Setup: skip the Claude Code wiring the ormah plugin already provides — Design
- test_delete_guarded.py
- single instance listener
- peerDependencies
- install
- devDependencies
- peerDependenciesMeta
- keywords
- run
- _legacy_archival
- Separate Surfaced Results from Confirmed Memory Use — Design
- Whisper golden corpus (golden/golden.jsonl, local-only)
- _load_state
- build
- verify release versions
- files
- install_pi_md
- `frozen_until` Implementation Plan — Overview
- Investigação consolidada — ingestão (2026-07-30, tarde)
- test graph focus
- Ormah Memory Dashboard — Design
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
- test_soft_delete_tombstone.py
- ingest-deferred-tracks.md
- Auditoria do ADR-0004 — 2026-08-09
- beta-keep (150 commits) — MUST survive the Task 6 merge (not in any PR, not upstream)
- Spec — isolate `test_setup.py` from the developer's machine
- LoggingHandler
- Draft comment for #209 — failure-mode analysis of the four-way duplicate policy
- run_whisper_log_cleanup
- TestStopOffsetCeiling
- TestMarkOutdated
- Port #221 (bounded reinforcement) onto local-main's post-#220 API — Implementation Plan
- Runbook — running against the archived data directory (`ormah_old`)
- Graph Node Size by Degree — Design
- Graph view: WebGL live-force migration (sigma.js)
- Design: session-watcher catch-up off the bind path (#52)
- LocalAdapter
- _edges_between
- Design — Graph active-first com drill-down de espaço (#22 slice 1)
- Design
- Design
- index_updater lock-order inversion — design
- ADR-0004 — repairing the two defects that break H1 in the ingest spool
- get_ormah_bin_path
- TestWhisperDebugMode
- run_consolidation
- Investigação — pipeline de whisper — 2026-07-15
- Setup: stop clobbering pre-existing user config
- LLM Cancellation Redesign — Single Global Epoch
- Path
- 2026-08-19-claude-cli-stable-cache-prefix/00-overview.md
- 01-lifecycle-and-knobs.md
- Handoff — ADR-0004 slice 3 (`no_safe_boundary`): plano revisado 5×, nada implementado (2026-07-28)
- ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the queue
- Design: Session Watcher Cursor Safety
- Whisper-health metric — design
- ormah-backup-ux-check.sh
- 02-record-confirmed-use.md
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
- Design — remove the wall-clock race from `test_hippocampus.py`
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
- 03-decay-manager.md
- Amendment 2026-08-13 — Fix B ships: suppression is a fact about the file, not a cursor advance
- Embedding Delta Backfill (#32) Implementation Plan — Overview
- Claude-CLI memory extraction — Implementation Plan (overview)
- ADR-0004 Spool H1 Repair — Overview
- 04-importance-anchor.md
- 2026-08-17-issue-221-port/05-lifecycle-model-version.md
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
- 2026-08-17-issue-221-port/06-docs.md
- Issue #232 — Explicit filter parameters on the recall boundary
- config.py
- hippocampus.py
- Problema 3 — o churn de `seq` (refutado como causa do backlog)
- Task 3 — Pure helpers: `buildSpaceLegend` + `scopeLabel`
- Bounded Stability Reinforcement (#221) — Implementation Plan
- LiteLLMEmbeddingAdapter
- Recovery drops an orphan fragment rather than re-ingesting the whole transcript
- ⛔ SUPERSEDED — this plan was split into three slices (2026-07-21)
- Task 4 — Wiring: `App.tsx` (estado + fetch) e `GraphView.tsx` (legenda drill + banner)
- Task 2: Add `_claude_code_plugin_provides_hooks()`
- Task 2: Always-on Ingest worker — drains the spool; Observer becomes optional
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
- start_hippocampus
- ormah-desktop
- _commit_updates_chunked
- init_key
- test_hybrid_search_raw_cosine.py
- test_index_embedding_retry.py
- test_migration_seq.py
- db.py
- 01-lifecycle-module.md
- 02-config-knobs.md
- 03-cooldown-reinforcement.md
- 04-decay-shared-retrievability.md
- 05-lifecycle-model-version.md
- 06-docs.md
- _save_state
- test_parse_transcript_breaks_before_overshooting_the_content_budget

## God Nodes (most connected - your core abstractions)
1. `Settings` - 204 edges
2. `MemoryEngine` - 150 edges
3. `CreateNodeRequest` - 146 edges
4. `NodeType` - 140 edges
5. `ContextBuilder` - 140 edges
6. `CloudProtectionService` - 119 edges
7. `parse_transcript()` - 96 edges
8. `_mark_idle()` - 93 edges
9. `load_state()` - 93 edges
10. `_make_node_dict()` - 85 edges

## Surprising Connections (you probably didn't know these)
- `Pi ormah-maintenance agent prompt (ormah_run_maintenance)` --semantically_similar_to--> `Shipped ormah-pi-maintenance agent prompt`  [INFERRED] [semantically similar]
  integrations/pi-plugin/agents/ormah-maintenance.md → src/ormah/agents/ormah-pi-maintenance.md
- `test_ephemeral_thread_connection_is_retired()` --uses--> `Database`  [INFERRED]
  tests/test_index/test_db_fd_lifecycle.py → src/ormah/index/db.py
- `test_migrate_normalizes_duplicate_payloads_and_preserves_candidate_ids()` --uses--> `Database`  [INFERRED]
  tests/test_index/test_feedback_schema.py → src/ormah/index/db.py
- `test_migration_adds_matched_pattern_to_an_existing_db()` --uses--> `Database`  [INFERRED]
  tests/test_index/test_whisper_decisions_migration.py → src/ormah/index/db.py
- `test_index_embedding_gives_up_without_raising()` --uses--> `CreateNodeRequest`  [INFERRED]
  tests/test_engine/test_index_embedding_retry.py → src/ormah/models/node.py

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

## Communities (561 total, 143 thin omitted)

### Community 0 - "ok"
Cohesion: 0.08
Nodes (21): fail(), ok(), play_finale(), Shared output formatting for CLI and setup — matches install.sh visual style., Play a ~2.5s terminal animation: 'ormah' dissolves into a sphere. TTY only —…, Reset color detection cache (for testing)., Section header: \\n==> msg (bold)., Success: [ok] msg (green). (+13 more)

### Community 1 - "test_session_watcher.py"
Cohesion: 0.03
Nodes (184): _ingest_session(), IngestResult, Why an ingest attempt did/didn't commit, so reconcile parks only files that…, Ingest a single JSONL session transcript if changed. ``boundary`` is the…, _append_assistant(), _append_codex_turn(), _append_pair(), _append_user() (+176 more)

### Community 2 - "main.py"
Cohesion: 0.07
Nodes (32): BaseHTTPMiddleware, AgentMiddleware, Request, Response, Request middleware for agent_id extraction and logging., begin_llm_lifespan(), cancel_active_llm_calls(), Cancel every in-flight LLM call. Returns how many calls the cancel invalidated.… (+24 more)

### Community 3 - "protection.py"
Cohesion: 0.07
Nodes (50): ProtectionState, key_file_exists(), _cleared_upload_journal(), _cloud_error_code(), _EnablePrerequisiteError, _existing_store_id(), _finalize_is_definitively_expired(), _is_disk_full_error() (+42 more)

### Community 4 - "product_bridge.rs"
Cohesion: 0.08
Nodes (76): account_status(), AccountStatus, backup_now(), billing_offer(), BillingOffer, bind_protection_intent(), cancel_protection_intent(), cancel_restore() (+68 more)

### Community 5 - "IngestSpool"
Cohesion: 0.04
Nodes (64): IngestSpool, Path, Durable ingest queue built from directory entries (ADR-0004 Amendment…, Enqueue a job. The boundary lives in the filename: a second, slower nudge for…, Claim the oldest due pending job. The rename IS the mutual exclusion. ⚠️ This…, Mark a job done. Idempotent: completing an already-completed job must not…, Return a claimed job to pending/, or dead-letter it, keyed on failure CLASS --…, Move a job to failed/ WITH its original bytes -- never unlink without first… (+56 more)

### Community 6 - "Pi Plugin Client"
Cohesion: 0.05
Nodes (41): ormahPi(), IngestBody, MaintenanceResults, OrmahClient, OrmahHttpError, RecallBody, RememberBody, WhisperResponse (+33 more)

### Community 7 - "CloudProtectionService"
Cohesion: 0.08
Nodes (87): Build a BackupService from a Settings-like object., service_from_settings(), Guarded scheduler adapters for shared cloud protection operations., Run one scheduled backup, swallowing every exception at the scheduler boundary., Run weekly verification, swallowing every exception at the scheduler boundary., run_cloud_backup(), run_restore_verification(), CloudProtectionService (+79 more)

### Community 8 - "rerank"
Cohesion: 0.05
Nodes (46): _linear_rescale(), Rescale raw CE score to [0, 1] using clamped linear interpolation., Rerank search results using a cross-encoder with linear-rescale blended…, rerank(), _candidate(), _linear_rescale(), Unit tests for the cross-encoder reranker with linear-rescale blended scoring.…, blend_alpha=1 means only CE matters. (+38 more)

### Community 9 - "memory_engine.py"
Cohesion: 0.05
Nodes (49): Automatic space/cluster assignment for unassigned nodes., Assign unassigned nodes to spaces based on their connections., run_auto_cluster(), Central facade for all memory operations., # NOTE: index_single calls _remove_node internally which wipes edges,, Tier promotion/demotion and core cap enforcement., Index builder: full rebuild and incremental updates from markdown files., The ingest extraction prompt contract: rules, response schema, rendered… (+41 more)

### Community 10 - "Tauri Sidecar Commands"
Cohesion: 0.06
Nodes (58): Command, base_url(), detect_agents(), fetch_stats(), graph_url(), is_onboarded(), mark_onboarded(), marker_path() (+50 more)

### Community 11 - "timedelta"
Cohesion: 0.05
Nodes (75): find_rotted_patterns(), live_patterns(), _proposed_action(), datetime, Detect synthetic-prompt patterns that stopped matching (#143). The #134…, Stable text derived ONLY from the pattern — this string is the dedup key. Never…, Propose corrections for synthetic patterns that went quiet (#143). Proposes,…, A live pattern that matched before and has now gone quiet. (+67 more)

### Community 12 - "test_config.py"
Cohesion: 0.05
Nodes (73): parametrize, Tests for config validation., Create settings with overrides, using a temp dir for memory_dir., council C2: constructing Settings must NEVER raise for this pair — `ormah…, _settings(), test_activation_decay_one_ok(), test_activation_decay_zero(), test_affinity_defaults() (+65 more)

### Community 13 - "test_whisper_context.py"
Cohesion: 0.05
Nodes (33): _make_settings_mock(), Tests for whisper context (involuntary recall injection)., Tests for the per-session prompt buffer in the whisper route., Buffer should accumulate prompts per session., Different session IDs should have independent buffers., Create a MagicMock settings object with affinity-related float attributes., Affinity boost rescues candidates that would otherwise be gated out., A candidate below the injection gate that receives a strong affinity boost… (+25 more)

### Community 14 - "load_state"
Cohesion: 0.13
Nodes (56): load_state(), ProtectionIntentStatus, ProtectionState, User-facing states for the paid backup protection journey., Load one store's state, distinguishing absence from unsafe existing data., Durable phases for an explicit Protect action., Update selected fields while preserving the rest of one store's state., update_state() (+48 more)

### Community 15 - "Ingest is async: the client nudges, the server owns the cursor and advances on job completion"
Cohesion: 0.18
Nodes (11): Amendment 2026-07-22 — the durable queue is a directory spool, not the Cursor alone (and not a job table), Amendment 2026-08-10 — the cause is found: the frozen-prefix jump is a WINDOWED-parse artefact, Amendment 2026-08-12 — the windowed-parse defect reproduces post-wipe; neither fix from 08-09/08-10 has shipped, Consequences, Considered options, Field observation 2026-07-27 — the `no_safe_boundary` dead-letter has 533 transcripts and no drain, Ingest is async: the client nudges, the server owns the cursor and advances on job completion, Narrowed: `_mark_frozen_prefix_consumed` is not the only writer of the `{end_offset}` shape (+3 more)

### Community 16 - "session_watcher.py"
Cohesion: 0.05
Nodes (70): _assistant_response_after_prompt(), _confidence(), _feedback_llm_judge_enabled(), _insert_affinity(), _insert_usage_signal(), _llm_feedback_judge_response_format(), _llm_judge_whisper_usage(), _node_usage_evidence() (+62 more)

### Community 17 - "context_builder.py"
Cohesion: 0.10
Nodes (19): _first_sentence_truncate(), _gate_score(), _has_topical_overlap(), _prompt_log_snippet(), ndarray, Builds whisper context for involuntary recall injection., Absolute relevance signal for gating decisions. Gates answer "is anything here…, Return the first sentence of content, capped to max_len. (+11 more)

### Community 18 - "GraphView.tsx"
Cohesion: 0.07
Nodes (37): BANNER_BTN_STYLE, BANNER_STYLE, clampZoomSliderValue(), DRILL_BTN_STYLE, GraphView, LEGEND_PANEL_STYLE, LEGEND_ROW_STYLE, LEGEND_SECTION_TITLE_STYLE (+29 more)

### Community 19 - "Settings"
Cohesion: 0.06
Nodes (5): BaseSettings, field_validator, Settings, TestGetAdapter, TestGetEncoderCaching

### Community 20 - "routes_agent.py"
Cohesion: 0.07
Nodes (59): delete, connect(), delete_node(), FeedbackRequest, get_clients(), get_insights(), get_maintenance_status(), get_proposals() (+51 more)

### Community 21 - "start_session_watcher"
Cohesion: 0.05
Nodes (61): The one spool-root path every caller must use -- never reach for /tmp. The…, A short stable hash identifying one watch root's spool. Roots must not share a…, root_key(), spool_root(), _configured_watch_roots(), _expand_watch_dir(), Build the always-on ingest worker for every acceptance root and return the…, Stop observers and fully drain in-flight ingests before returning. The lifespan… (+53 more)

### Community 22 - "test_claude_cli_adapter.py"
Cohesion: 0.07
Nodes (60): ClaudeCliAdapter, LlmCancelledError, The call was cancelled by the host (shutdown/stop), not by the provider. Says…, _fake_popen(), _pid_alive(), integration, skipif, Belt-and-suspenders against the real binary: an operator SessionStart hook must… (+52 more)

### Community 23 - "recovery.py"
Cohesion: 0.14
Nodes (16): extract_recovery_kit_format_version(), Return one declared kit format version, or None for a legacy kit., datetime, Path, Recovery-kit validation and device-loss readiness confirmation. This is the…, Validate the canonical kit and confirm a reopened native saved copy., Validate the fixed canonical kit without changing readiness., Repair a stale canonical kit before a native save operation. Returns ``True``… (+8 more)

### Community 24 - "CloudState"
Cohesion: 0.07
Nodes (65): _as_utc(), cloud_status_payload(), CloudState, CloudStateLoadError, CloudStateVersionError, _ensure_writable_schema(), _existing_store_id(), is_device_loss_recovery_ready() (+57 more)

### Community 25 - "routes_account.py"
Cohesion: 0.08
Nodes (53): account_checkout(), _account_http_error(), account_logout(), account_offer(), account_portal(), account_request_code(), account_status(), account_verify_code() (+45 more)

### Community 26 - "SessionHandler"
Cohesion: 0.04
Nodes (65): _commit_state(), _default_acceptance_roots(), _file_hash(), _frozen_unchanged(), _is_nested_or_equal(), _is_subagent_transcript(), _load_state(), ParkOutcome (+57 more)

### Community 27 - "run_conflict_detection"
Cohesion: 0.08
Nodes (55): _conflict_scope_value(), _find_conflict_candidates(), Find node pairs that might contradict each other. ``delta=False`` (default —…, Find potentially contradicting nodes and create edges. Seeds are delta-selected…, run_conflict_detection(), _conflict_response(), _create_pair(), _make_belief() (+47 more)

### Community 28 - "store_lock.py"
Cohesion: 0.17
Nodes (16): canonical_memory_dir(), _entry_for(), _LockEntry, Path, Cross-process lock for operations that act on one local memory store., Return the stable local identity used for locking one memory directory., Return the lock path without consulting cloud enrollment or ``store_id``., store_lock_path() (+8 more)

### Community 29 - "test_session_watcher_flush.py"
Cohesion: 0.04
Nodes (44): _FakeConn, fixture, Presence detection must not fire on a commented-out line or on a longer key…, Review M-9: the repo owner's ordered fix (warn instead of silently `continue`…, Regression for review F1: with no ~/.config/ormah/.env and no ./.env,…, The F1 fix must not over-correct into swallowing a REAL read failure…, Council R1 (Cursor): a floor of `>= flush_chars` compares bytes to chars and…, A single turn bigger than the budget can't make empty progress — commit it as… (+36 more)

### Community 30 - "NodeType"
Cohesion: 0.04
Nodes (95): One-time migration: fix identity node tiers and edges. Phase 1…, Connection, MemoryNode, NodeType, BaseModel, Advance `updated`. Call before saving any content mutation; never for read-side…, BaseModel, Search-related models. (+87 more)

### Community 31 - "test_eval_whisper/test_metrics.py"
Cohesion: 0.07
Nodes (21): compute_prompt_metrics(), f1_score(), has_false_positive(), injection_precision(), injection_recall(), Metrics for whisper eval: injection recall, precision, f1, top2_recall,…, Fraction of injected nodes that were relevant. By default, relevance is defined…, Fraction of should_inject nodes in top-2 injected positions (shown in full). (+13 more)

### Community 32 - "test_duplicate_merger.py"
Cohesion: 0.09
Nodes (47): Find near-duplicate nodes and create merge proposals. Uses a multi-signal…, run_duplicate_detection(), _create_pair(), _duplicate_response(), _make_fact(), Tests for LLM-based duplicate consolidation in duplicate_merger., With llm_provider='none', LLM is never called., For medium-confidence pairs, proposal contains merged content preview. (+39 more)

### Community 33 - "JobTracker"
Cohesion: 0.08
Nodes (40): JobStatus, JobTracker, Any, Track background job execution status for observability., Wrap a job function with tracking. Returns a no-arg callable for the scheduler., Snapshot of a single job's health., Thread-safe registry of background job execution outcomes., Yield True if this caller claimed the job, False if it was already running. An… (+32 more)

### Community 34 - "llm/__init__.py"
Cohesion: 0.08
Nodes (34): LLMAdapter, Abstract base class for LLM adapters., Send *prompt* to the LLM and return the raw response text. Returns ``None`` on…, Interface that all LLM backends must implement., Claude CLI LLM adapter — headless `claude -p` via subscription auth (no paid…, _get_or_create_adapter(), get_adapter(), LLM adapter package — pluggable backends for background jobs. (+26 more)

### Community 35 - "ormah/cli.py"
Cohesion: 0.05
Nodes (81): cmd_eval_recall_import_labels(), main(), Entry point for MCP stdio server., _backup_service(), _backup_to_dict(), _cloud_client(), _cmd_account_login(), _cmd_account_logout() (+73 more)

### Community 36 - "Tauri Bundle Config"
Cohesion: 0.04
Nodes (46): app, security, windows, withGlobalTauri, build, beforeBuildCommand, frontendDist, bundle (+38 more)

### Community 37 - "test_whisper_out.py"
Cohesion: 0.09
Nodes (27): Find a transcript JSONL for a session ID across supported clients., _resolve_transcript_path(), _isolate_cache(), _make_transcript(), _mock_client(), _outbox_records(), fixture, Tests for whisper-out: the PreCompact/SessionEnd hook is a pure /ingest/nudge… (+19 more)

### Community 38 - "IndexBuilder"
Cohesion: 0.13
Nodes (16): Row, IndexBuilder, Path, Update index for changed/new files. Returns (added, updated) counts., Builds and updates the SQLite index from markdown source files., Index or re-index a single file., The stored fingerprint + seq, read BEFORE _remove_node deletes the row. Only…, Index a single markdown file into the database (nodes + edges). (+8 more)

### Community 39 - "test_confirmed_use_contract.py"
Cohesion: 0.06
Nodes (63): fts_only(), _make_nodes(), fixture, parametrize, Contract tests for issue #220: surfacing must not be confirmed use. Every…, Contract 5: the UI search route. This is the test that fails on clean…, Contract 6: whisper still mutates nothing after losing its flag. Whisper was…, Issue #220: _record_confirmed_use is atomic across its read-modify-write.… (+55 more)

### Community 40 - "open_bundle"
Cohesion: 0.11
Nodes (47): build_bundle(), BundleError, open_bundle(), RuntimeError, Decrypt, safely extract, and hash-verify a bundle into dest_dir. Any manifest…, Raised when building or opening a bundle fails., Build an encrypted bundle from a finished local backup directory. Returns the…, _dir_hashes() (+39 more)

### Community 41 - "GraphIndex"
Cohesion: 0.09
Nodes (14): GraphIndex, Any, Query nodes by created timestamp, ordered by created DESC. Returns up to…, Full-text search using FTS5. Uses AND semantics for multi-token queries (all…, Graph queries on the SQLite index., Fetch multiple nodes in a single query, keyed by ID., Fetch tags for multiple nodes in a single query, keyed by node ID., Get neighbors up to `depth` hops using recursive CTE. (+6 more)

### Community 42 - "forgetting_manager.py"
Cohesion: 0.13
Nodes (30): _archival_rows(), _aware(), _backfill_legacy_archived_at(), _cap_guard(), _connectivity(), _eligibility_guard(), _evaluate_protection(), _forget_score() (+22 more)

### Community 43 - "CloudCryptoError"
Cohesion: 0.19
Nodes (25): Identity, Recipient, CloudCryptoError, decrypt_bytes(), encrypt_bytes(), generate_identity(), identity_from_str(), RuntimeError (+17 more)

### Community 44 - "CLI Adapter Tests"
Cohesion: 0.08
Nodes (44): _mock_response(), Tests for the CLI adapter., Run the CLI with given args, returning (exit_code, stdout, stderr)., Create a mock httpx.Response., When cwd is missing, space should be None (no space key in body)., Nudge appears at the Nth prompt (default 10)., Nudge never appears when interval is 0., Each session_id gets its own counter. (+36 more)

### Community 45 - "._builder"
Cohesion: 0.18
Nodes (7): Standing rules use a typed applicability channel without biasing facts., Topic-shift suppression only fires for topics that were served (I9)., Turn 1 was gate-rejected (logged was_injected=0); turn 2 on the same topic must…, Turn 1 injected (was_injected=1); turn 2 on the same topic is correctly…, Without a session_id there is no served history — the plain topic-shift skip…, TestPreferenceApplicability, TestTopicShiftServedMemory

### Community 46 - "api.ts"
Cohesion: 0.10
Nodes (40): AdminTask, AgentInfo, BackupInfo, BackupStatus, CloudStatus, createBackup(), del(), fetchAdminTasks() (+32 more)

### Community 47 - "routes_admin.py"
Cohesion: 0.10
Nodes (42): HTTPException, _backup_service_from_request(), backup_status(), _backup_status_payload(), _backup_to_dict(), BackupSettingsUpdate, cloud_status(), create_backup() (+34 more)

### Community 48 - "run_setup"
Cohesion: 0.08
Nodes (30): backfill_transcripts(), configure_llm(), _cost_hint(), _disable_llm(), _discover_transcripts(), _enable_llm(), _estimate_cost(), _persist_env_delta() (+22 more)

### Community 49 - "ContextBuilder"
Cohesion: 0.05
Nodes (41): ContextBuilder, Builds agent context from core memories., _make_node_dict(), Whisper formatting: flat list, top 2 full, rest title-only., Topic-shift detection: skip injection when prompt is on the same topic., High similarity to recent prompts → skip whisper., Low similarity to recent prompts → proceed with whisper., Underspecified follow-up prompts should still search even on same topic. (+33 more)

### Community 50 - "ui/src/App.tsx"
Cohesion: 0.09
Nodes (31): App(), DEFAULT_EDGE_TYPES, Filters, PanelId, ThemeTransitionState, EDGE_TYPES, FilterDrawer(), Props (+23 more)

### Community 51 - "billing.py"
Cohesion: 0.10
Nodes (35): BaseException, NoReturn, BillingError, BillingErrorCode, BillingOffer, _canonical_account_id(), _canonical_uuid4(), CheckoutHandoff (+27 more)

### Community 52 - "test_ingest_extraction.py"
Cohesion: 0.05
Nodes (42): Split content into pieces at line (turn) boundaries; each piece is <=hard_cap.…, _split_for_extraction(), Extraction error classification: timeout/call-failure must not read as 'no…, If every chunk's call fails while a provider is configured, the whole…, Extracted memories below ingest_min_confidence are dropped before node creation., A single line (turn) longer than hard_cap is split into <=hard_cap pieces,…, An oversized turn between normal turns is split without dropping any turn or…, A variable payload against a fixed provider timeout is the bug. The hint must… (+34 more)

### Community 53 - "_insert_node"
Cohesion: 0.10
Nodes (25): _find_review_candidate(), Find a gated-out whisper candidate eligible for session-start review. Applies…, _insert_node(), _make_node_dict(), Tests for the review mechanism in build_whisper_context., was_injected=0 row within 7 days returns a candidate dict., Node with both was_injected=0 and was_injected=1 within 7 days is excluded., Tests for the Python-side filtering in _find_review_candidate. (+17 more)

### Community 54 - "test_main_lifespan_shutdown.py"
Cohesion: 0.10
Nodes (20): _fake_lifespan_deps(), asyncio, fixture, Bounded scheduler shutdown + engine.shutdown() policy (Fix A / Fix D). Tests…, R1: each lifespan execution must create a NEW threading.Event in…, Patch main.lifespan's heavy dependencies. Mirrors the fakes at L249-288., R7 HIGH-2 regression. When start_session_watcher() raises, main.lifespan…, The adapter caches and the cancellation epoch are module-level and outlive a… (+12 more)

### Community 55 - "FileStore"
Cohesion: 0.09
Nodes (29): FileStore, MemoryNode, Path, File-based CRUD for memory nodes stored as markdown files., Move a node file to the deleted/ directory, stamping deleted_at atomically. The…, List tombstones in deleted/ as (node_id, deleted_at, path)., Hard-delete a tombstone from deleted/. Returns True if removed. Pass ``path``…, Load all nodes from disk. (+21 more)

### Community 56 - "productBridge.ts"
Cohesion: 0.07
Nodes (56): ACTION_ICONS, errorMessage(), formatDate(), formatPrice(), LoginPurpose, operationIsActive(), operationLabel(), operationSuccessMessage() (+48 more)

### Community 57 - "dependencies"
Cohesion: 0.05
Nodes (41): graphology, graphology-layout, graphology-layout-forceatlas2, jsdom, lucide-react, sigma, @tauri-apps/api, dependencies (+33 more)

### Community 58 - "setup.py"
Cohesion: 0.05
Nodes (45): _claude_code_detected(), _claude_code_unwire(), _claude_desktop_unwire(), _codex_detected(), configure_pi_extension(), _enable_codex_feature(), _find_binary(), _is_ormah_pi_source() (+37 more)

### Community 59 - "backup.py"
Cohesion: 0.08
Nodes (39): BackupInfo, BackupError, BackupInfo, BackupService, _count_backupable_markdown(), _count_markdown(), _directory_size(), _infer_user_node_id() (+31 more)

### Community 60 - "Design — ingest Batch budgeted on conversation length (ADR-0001 Amendment 3)"
Cohesion: 0.04
Nodes (39): Definition of done, File structure, Global Constraints, Ingest Batch Content Budget — Implementation Plan (overview), Out of scope (registered elsewhere, do not pick up), Rollout note, Tasks, The trap that will bite (+31 more)

### Community 61 - "local_auth.py"
Cohesion: 0.14
Nodes (18): load_or_create_local_admin_token(), Path, Request, Owner-only capability authentication for sensitive local API routes., Load this installation's local API capability, creating it mode 0600., Reject sensitive requests that did not originate on this machine., Authenticate a native local caller without exposing the cloud account token., require_local_admin() (+10 more)

### Community 62 - "test_ingest.py"
Cohesion: 0.06
Nodes (28): _canned(), integration, parametrize, skipif, Tests for conversation ingestion: dry_run, confidence, truncation., Real claude_cli round-trip: mandatory schema must survive an actual `claude -p`…, dry_run=True should return extracted memories without calling remember()., Verify no nodes are created during dry_run. (+20 more)

### Community 63 - "test_temporal_search.py"
Cohesion: 0.14
Nodes (13): _make_node(), mock_hybrid(), fixture, Tests for temporal query filters (created_after / created_before)., Temporal + type filters should combine with AND semantics., HybridSearch with mocked internals — no real DB or encoder., Run search with all three nodes returned by both retrievers., _run_search() (+5 more)

### Community 64 - "run_uninstall"
Cohesion: 0.08
Nodes (20): _cloud_recovery_paths(), CloudRecoveryPreflight, CloudRecoveryPreflightError, _prepare_cloud_recovery(), RuntimeError, Return recovery artifacts that uninstall must never delete., Raised when uninstall cannot prove cloud backups remain recoverable., Recovery artifacts verified before destructive uninstall work begins. (+12 more)

### Community 65 - "ProtectionOperationKind"
Cohesion: 0.10
Nodes (32): get_or_create_store_id(), UUIDv4 per memory store, persisted at <memory_dir>/.store_id., LocalOperation, LocalOperationStatus, ProtectionOperationCoordinator, datetime, ProtectionOperation, StrEnum (+24 more)

### Community 66 - "test_spreading_activation.py"
Cohesion: 0.11
Nodes (38): _excerpt(), _feedback_id_suffix(), format_node(), format_node_with_neighbors(), format_search_results(), Any, Format graph data as human/agent-readable text., Format a single node as readable text. (+30 more)

### Community 67 - "TestClient"
Cohesion: 0.08
Nodes (34): TestClient, build_client(), client(), fake_client(), FakeCloudClient, fixture, parametrize, Tests for local account-linked billing handoffs. (+26 more)

### Community 68 - "CloudClient"
Cohesion: 0.09
Nodes (40): BaseTransport, CloudClient, CloudError, Any, RuntimeError, Small synchronous client for the metadata-only Ormah Cloud API., Return validated, display-safe subscription price metadata., Start or resolve a Stripe Checkout session for a pending Protect intent. (+32 more)

### Community 69 - "routes_protection.py"
Cohesion: 0.07
Nodes (62): backup_now(), bind_intent(), cancel_intent(), cancel_restore(), confirm_recovery_kit(), confirm_restore(), ConfirmRecoveryKitRequest, _coordinator() (+54 more)

### Community 70 - "install_autostart"
Cohesion: 0.15
Nodes (12): CalledProcessError, _called_process_error_output(), install_autostart(), install_launchd_agent(), install_systemd_service(), Install and load a launchd agent for auto-starting the server on macOS., Install and enable a user-space systemd service for auto-starting the server., Start the server as a background process (fallback when no init system). (+4 more)

### Community 71 - "test_eval_recall/test_metrics.py"
Cohesion: 0.10
Nodes (36): compute_case_metrics(), f1_at_k(), false_negative_rate(), false_positive_present(), mrr(), precision_at_k(), Precision, recall, and related retrieval metrics for recall eval., Compute all metrics for a single (prompt, results) pair. injection_fired: True… (+28 more)

### Community 72 - "test cleanup auto ingested"
Cohesion: 0.13
Nodes (29): main(), _node_source(), plan_cleanup(), _print_table(), Path, Perform the destructive cleanup. Returns a process exit code. Steps:…, run_cleanup(), _FakeBackupService (+21 more)

### Community 73 - "run_auto_linker"
Cohesion: 0.13
Nodes (24): _get_watermark(), Automatic edge creation based on embedding similarity., Render one candidate pair for a batched link prompt (#87)., Return the seq of the last fully-processed node, or 0 if unset., Nodes with seq strictly greater than the watermark, ascending, bounded., Incrementally link nodes with seq above the watermark, judging candidate pairs…, _render_link_pair(), run_auto_linker() (+16 more)

### Community 74 - "cli_adapter.py"
Cohesion: 0.15
Nodes (26): _api(), _client(), cmd_ingest(), cmd_ingest_session(), cmd_node(), cmd_outdated(), cmd_recall(), cmd_remember() (+18 more)

### Community 75 - "_claude_code_plugin_provides_hooks"
Cohesion: 0.06
Nodes (28): _claude_code_is_wired(), _claude_code_plugin_provides_hooks(), True when a user-scoped ormah plugin is enabled AND actually installed. Claude…, Path, Regression: the hooks branch read entry.get("command") off the matcher dict, so…, The plugin provides the hooks and MCP server; without this the UI would report…, Nothing would actually fire — reporting 'wired' would be a lie., Verify that run_uninstall deletes the actual memory directory regardless of… (+20 more)

### Community 76 - "ConnectRequest"
Cohesion: 0.07
Nodes (44): _apply_consolidation(), _cluster_signature(), _consolidate_cluster(), Background job: consolidate clusters of similar working-tier memories via LLM., Create a consolidated node, link originals, and demote them to archival.…, Consolidate a single cluster using LLM summarization., Content signature of a cluster: changes if any member's id/title/content/…, _record_signature() (+36 more)

### Community 77 - "test_seq_fingerprint.py"
Cohesion: 0.10
Nodes (35): _make_node(), Conditional seq allocation driven by a persisted content fingerprint (#126)., auto_cluster dual-writes `space`: straight into SQLite AND into the markdown., Content feeds the embedding and the judge prompt., Type is shown to the LLM judge., Tags feed FTS, never the linker., A row whose file on disk no longer matches its file_hash has a pending reindex.…, A row whose file matches its hash is stamped, so the upgrade does not requeue… (+27 more)

### Community 78 - "configure_codex_mcp"
Cohesion: 0.11
Nodes (14): _codex_wire(), configure_codex_mcp(), install_codex_agents(), Remove ormah entry from ~/.codex/config.toml., Remove a top-level TOML table block while preserving surrounding content., Write or update the Ormah MCP entry in ~/.codex/config.toml., Register Ormah MCP server in Codex config., Install Ormah custom agent definitions into ~/.codex/agents/. (+6 more)

### Community 79 - "test feedback schema"
Cohesion: 0.11
Nodes (34): _index_exists(), _make_db_without_new_tables(), _make_legacy_affinity_db(), Path, Tests for whisper_log, affinity, and review_log schema additions., Feedback is capped per whisper event, not per whole session., Create a DB, init schema, then drop the three new tables to simulate an older…, Calling _migrate() on an already-migrated DB must not raise. (+26 more)

### Community 80 - "test_hybrid_search.py"
Cohesion: 0.03
Nodes (90): _is_question_query(), Any, Hybrid search combining FTS5 + vector search with Reciprocal Rank Fusion. Uses…, Detect whether a query is a natural language question., Fuse multiple ranked lists using weighted Reciprocal Rank Fusion. Each list…, Hybrid search with Reciprocal Rank Fusion. ``query_vec`` may be supplied by a…, _reciprocal_rank_fusion(), Graph traversal queries using recursive CTEs. (+82 more)

### Community 81 - "FastAPI"
Cohesion: 0.09
Nodes (21): FastAPI, app_and_client(), fixture, The manual task-trigger routes must not start a job that is already running,…, A manual trigger during the scheduled run used to start a second concurrent run…, The route returned {'status': 'completed'} unconditionally — a run that blew up…, run-all calls the runners directly too — same hole., The guard is only atomic against a SHARED tracker. It was created inside the… (+13 more)

### Community 82 - "RecoveryKitError"
Cohesion: 0.11
Nodes (20): Client-side cloud primitives: encryption, snapshot bundles, key lifecycle.…, RuntimeError, Raised when recovery material cannot be proven current and complete., RecoveryKitError, fixture, parametrize, Path, recovery_store() (+12 more)

### Community 83 - "validate_case"
Cohesion: 0.11
Nodes (13): CorpusError, load_corpus(), Exception, Path, Load and validate whisper eval corpus files (JSONL format)., Raised on corpus file or validation errors., Load a JSONL corpus file. Skips blank lines. Validates each case., Validate a single corpus case. Raises CorpusError on structural issues. (+5 more)

### Community 84 - "run_forgetting"
Cohesion: 0.13
Nodes (47): Soft-delete dead-weight archival nodes, then purge expired tombstones., run_forgetting(), _archival_count(), _backdate_tombstone(), _break(), _enable(), _exists(), _make_archival_recent() (+39 more)

### Community 85 - "llm_client.py"
Cohesion: 0.08
Nodes (33): _get_or_create_ingest_adapter(), ingest_llm_generate(), ingest_provider_configured(), Shared LLM facade for background tasks. All callers import ``llm_generate``…, Ingest path: PROPAGATE LlmCancelledError. The engine maps it to a provider-wide…, True when a server-side extraction adapter is available (ingest provider !=…, Clear the cached adapters (useful for test isolation)., reset_adapter() (+25 more)

### Community 86 - "get_fastembed_cache_dir"
Cohesion: 0.15
Nodes (16): get_fastembed_cache_dir(), is_model_cached(), Path, Helpers for locating and inspecting the shared Ormah model cache., Return the effective shared model cache directory., Return True when the model's expected fastembed cache directory exists., _get_model(), model_is_cached() (+8 more)

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
Nodes (16): safe_* must exclude a dangling user turn; raw fields still include it., A trailing pair with NO completion signal (no stop_reason field) is not safe…, tool_use followed by a text assistant must form ONE pair, not fragment. The…, A multi-record assistant response at EOF must not be committed mid-stream. The…, Once the next user turn arrives, the full multi-record response is one safe…, A terminal stop_reason (Claude Code) closes the response immediately — the safe…, A multi-record response (tool_use then end_turn) is one safe pair, never split…, A slice that begins with assistant records (a cursor left mid-response by an… (+8 more)

### Community 91 - "recall/cli.py"
Cohesion: 0.14
Nodes (17): _check_fail_below(), _check_regression(), cmd_eval_recall_export_for_labeling(), cmd_eval_recall_run(), _corpus_files_for_label(), _make_engine(), Path, CLI handlers for `ormah eval recall` commands. (+9 more)

### Community 92 - "SessionWatch"
Cohesion: 0.11
Nodes (23): Re-admit new LLM calls after a RECOVERABLE cancel (the watcher's startup…, resume_llm_adapters(), _drain_handlers(), A live watch root: its directory, always-on handler + spool, and — only when…, Poll until no handler has an in-flight ingest, so nothing touches the DB after…, Shared shutdown/rollback sequence (ADR-0004 slice 2): stop, cancel (rollback-…, Periodic safety net: recreate any dead Observer, then reconcile each DISCOVERY…, run_session_reconcile() (+15 more)

### Community 93 - "restore.py"
Cohesion: 0.12
Nodes (38): RestoreProgress, Result of restoring a memory backup., RestoreResult, _candidate_blobs(), cleanup_abandoned_cloud_restores(), CloudRestoreError, CloudRestoreResult, CloudRestoreValidationError (+30 more)

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

### Community 98 - "2026-08-19-hippocampus-flake-condition-waiting/00-overview.md"
Cohesion: 0.15
Nodes (8): File Structure, Global Constraints, Tasks, test_hippocampus Condition-Based Waiting — Implementation Plan, Task 1: Build the clean island, Task 2: `_wait_until` and the ingestion wait (line 83), Task 3: The debounce wait (line 169), Task 4: Verify against the baseline and ship

### Community 99 - "run_whisper_eval"
Cohesion: 0.19
Nodes (6): Run the whisper eval pipeline over *cases*., run_whisper_eval(), integration, End-to-end integration coverage for the whisper eval harness., test_run_whisper_eval_end_to_end_with_real_engine(), TestRunWhisperEval

### Community 100 - "test_mutation_stamping.py"
Cohesion: 0.18
Nodes (27): _backdate(), _create(), Mutation-stamping guarantees (Sync v1 Step 0). Every content mutation must…, Create a node with auto-linking suppressed, return its id., Phase-2 repaired defines edges must live in the self node's markdown so they…, Parse the tombstone file for a node from deleted/., _reset_adapter(), test_auto_cluster_advances_updated() (+19 more)

### Community 101 - "start_scheduler"
Cohesion: 0.09
Nodes (28): BackgroundScheduler, Vector-store reconciliation job: backfill missing embeddings (#32)., Reconcile the vector store. Raises if the store is left incomplete. Unlike the…, run_embedding_backfill(), datetime, Event, APScheduler job registration for background processing., One shared factor for all four jobs, so distinct nominal offsets stay distinct… (+20 more)

### Community 102 - "whisper/cli.py"
Cohesion: 0.11
Nodes (26): _check_fail_below(), cmd_eval_whisper_import_labels(), cmd_eval_whisper_mine(), _make_engine(), CLI handler for `ormah eval whisper run`., Parse 'f1=0.65,suppression=0.90' and check thresholds. Returns 1 if any fails.…, _connect_ro(), _draft_expected() (+18 more)

### Community 103 - "bundle.py"
Cohesion: 0.14
Nodes (18): main(), Path, sha_map(), step(), _add_member(), BundleInfo, _check_dest(), _iter_bundle_files() (+10 more)

### Community 104 - "test_routes.py"
Cohesion: 0.08
Nodes (14): health(), Tests for API routes., CH2: with no scheduler, a degraded fallback makes /admin/health degraded., Inverse: a healthy fallback (flag False) leaves health ok., Issue #90 (dev council follow-up): a Phase 1 with a broken finder must still…, CR2: scheduler present + embedding_backfill last run failed -> health degraded., A later success after an error leaves health ok., test_health_degraded_when_no_scheduler_and_fallback_failing() (+6 more)

### Community 105 - "desktop ui package"
Cohesion: 0.07
Nodes (26): dependencies, framer-motion, react, react-dom, devDependencies, @types/react, @types/react-dom, typescript (+18 more)

### Community 106 - "TierManager"
Cohesion: 0.23
Nodes (7): MemoryNode, Manages tier transitions and enforces the core memory cap., Promote a node to a higher tier. Returns True if promoted., Demote a node to a lower tier. Returns True if demoted., If core nodes exceed the cap, demote least-accessed ones to working. Nodes in…, TierManager, Tier

### Community 107 - "whisper/runner.py"
Cohesion: 0.17
Nodes (16): _collect_failures(), _fmt(), format_report(), Format whisper eval results as a human-readable table., _aggregate(), _aggregate_by_category(), PromptResult, Whisper eval runner — seeds DB, calls full pipeline, collects metrics per… (+8 more)

### Community 108 - "parse_transcript"
Cohesion: 0.16
Nodes (8): parse_transcript(), Parse a supported JSONL transcript into cleaned conversation text. Reads line…, Path, Write a list of dicts as JSONL to a temp file and return the path., A trailing tool-only assistant (no text) leaves the pair pending (known…, If the user interrupts a non-terminal response, the next user turn still closes…, TestParseTranscript, _write_jsonl()

### Community 109 - "test_cloud_cli.py"
Cohesion: 0.05
Nodes (42): cloud_paths(), fixture, CLI tests for the `ormah cloud` group., `ormah cloud kit` is the recovery path when init/rotate is interrupted between…, Fresh-machine import must adopt the kit's store id, not mint a new one — the…, Point every cloud path at tmp and return the key path., A damaged store_id line must abort the whole import before any key material is…, _run() (+34 more)

### Community 110 - "get_watermark"
Cohesion: 0.16
Nodes (17): _llm_check_conflict(), Detect contradictions between memory nodes., Render one candidate pair for a batched conflict prompt (#87)., Ask LLM whether two nodes contradict each other. Returns parsed dict or None if…, _render_conflict_pair(), get_watermark(), Shared seq-watermark helpers for incremental background jobs (#81). Generalizes…, Return the seq of the last fully-processed node for *key*, or 0. (+9 more)

### Community 111 - "CreateNodeRequest"
Cohesion: 0.03
Nodes (107): FSRS retrievability-based tier demotion for stale working memories., Auto-demote working nodes whose FSRS retrievability drops below threshold.…, run_decay(), Background job: recompute importance scores for all memory nodes., Importance recency: half-life decay on its own clock (#222). Independent of…, Iterate all nodes, compute weighted importance, persist changes., _recency_signal(), run_importance_scoring() (+99 more)

### Community 112 - "seed_case"
Cohesion: 0.21
Nodes (17): clear_eval_db(), datetime, Seed the isolated recall eval DB with memories from a corpus case., Return a created datetime for *mem*, or None for 'now'. Supports ``created``…, Clear eval DB and seed with memories from *case*. Memories are inserted with…, Remove all nodes from the eval DB and file store., seed_case(), _seed_created() (+9 more)

### Community 113 - "setup_logging"
Cohesion: 0.13
Nodes (21): LogRecord, _JSONFormatter, Path, Logging configuration — text or JSON format., Configure the root logger. Args: log_format: ``"text"`` for human-readable…, Redact known API-key values from log text., Redact strings inside JSON log extras without changing non-secret types., Text formatter that redacts API-key values from the final rendered line. (+13 more)

### Community 114 - "test_setup.py"
Cohesion: 0.06
Nodes (22): _codex_unwire(), _print_setup_summary(), Remove Ormah agent definitions from ~/.codex/agents/., Remove ormah whisper hooks from ~/.codex/hooks.json., Remove ormah whisper hooks from ~/.claude/settings.json., Remove the ormah instructions block from the active Codex AGENTS file., Remove Ormah hook entries while preserving every untouched matcher. Returns the…, _remove_claude_hooks() (+14 more)

### Community 115 - "test_backup.py"
Cohesion: 0.23
Nodes (21): _active_self(), MemoryNode, Path, _save_node(), _save_self_node(), _service(), _set_active_self(), test_auto_backup_creates_only_when_due() (+13 more)

### Community 116 - "extract_time_params"
Cohesion: 0.16
Nodes (9): extract_time_params(), Parse lightweight time references and return…, Backwards-compatible wrapper around module-level :func:`extract_time_params`., Tests for extract_time_params (bounded time windows)., last 2 weeks' uses rolling previous-period: 4w ago → 2w ago., last 1 week' (N=1) extends to now, not rolling., last 3 months' uses rolling: 6m ago → 3m ago., PromptClassifier._extract_time_params still works. (+1 more)

### Community 117 - "_make_engine_with_encoder"
Cohesion: 0.11
Nodes (13): _make_engine_with_encoder(), Create a mock engine with a hybrid search encoder that returns a fixed vector., The injection gate cuts absolute signals (ce_absolute / raw_cosine), never the…, A weak query's least-bad match: blended ~0.9 (rank-relative top) but the cross-…, A genuinely relevant match under-ranked by the bi-encoder: the cross-encoder…, Without the reranker, the gate falls back to raw_cosine, not the blended score., Results carrying neither absolute signal keep pre-contract gate behavior…, The gate re-applies cross-space demotion the absolute signal drops: a wrong-… (+5 more)

### Community 118 - "PromptIntent"
Cohesion: 0.07
Nodes (22): PromptIntent, Result of classifying a user prompt., TestPromptIntent, Precision helpers should favor the most relevant whisper candidate., Context-enhanced search using recent prompts., Underspecified follow-up prompts should use recent context in search., The reranker must score the same context-enhanced query that search ran on, not…, Fully specified prompts should not be polluted by recent context. (+14 more)

### Community 119 - "PromptClassifier"
Cohesion: 0.08
Nodes (22): PromptClassifier, Classify prompt intent using cosine similarity to archetype embeddings. Lazy-…, Classify *prompt* and return an intent with search-param overrides., ControlledEncoder, FakeEncoder, ndarray, Tests for the embedding-based prompt intent classifier., Test classification decisions with controlled cosine similarities. (+14 more)

### Community 120 - "mcp_adapter.py"
Cohesion: 0.12
Nodes (23): AsyncClient, Server, _coerce_list(), create_mcp_server(), _dispatch(), _format_maintenance_batches(), _format_timeout_error(), _handle_error() (+15 more)

### Community 121 - "compilerOptions"
Cohesion: 0.08
Nodes (23): compilerOptions, allowImportingTsExtensions, baseUrl, isolatedModules, jsx, lib, module, moduleResolution (+15 more)

### Community 122 - "background/__init__.py"
Cohesion: 0.13
Nodes (16): main(), CLI: python -m eval.maintenance.cli {mine|run|report} ... Local A/B eval gate…, _connect_ro(), mine_pairs(), Mine auto-link candidate pairs from a production store, read-only (#87 eval).…, agreement(), Agreement metrics for the single-vs-batched maintenance eval (#87 gate). Gate…, _load_pairs() (+8 more)

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

### Community 131 - "run_eval"
Cohesion: 0.19
Nodes (16): _aggregate(), _eval_case(), EvalResult, Recall eval runner: orchestrates per-case seeding, retrieval, and scoring., Compute aggregate metrics across all prompt results. Returns None for each…, Run the recall eval pipeline over *cases*. Returns EvalResult with per-case and…, Seed and evaluate a single corpus case., run_eval() (+8 more)

### Community 132 - "extract_json"
Cohesion: 0.15
Nodes (19): _llm_check_duplicate(), Ask LLM whether two nodes are duplicates and get merged content. Returns parsed…, extract_json(), Extract a JSON document from an LLM response. Thinking-capable models (e.g.…, Tests for fence-tolerant LLM JSON parsing shared across background jobs.…, A fenced-but-valid classification must yield the real relationship, not an…, Genuinely unparseable output (no JSON anywhere) yields an "error" result, never…, test_auto_linker_recovers_fenced_response_instead_of_poisoning() (+11 more)

### Community 133 - "MemoryEngine facade"
Cohesion: 0.12
Nodes (21): Eval gating deliberately excluded from CI, ContextBuilder, FileStore, GraphIndex, IndexBuilder, Markdown is the source of truth, MemoryEngine facade, Write path (+13 more)

### Community 134 - "APScheduler background scheduler"
Cohesion: 0.13
Nodes (21): Connection (typed weighted edge), Core cap enforcement (50 nodes), CreateNodeRequest, EdgeType and activation factors, FSRS stability field, MemoryNode, Proposal (merge/conflict/decay), Tier (core / working / archival) (+13 more)

### Community 135 - "test_account_auth_routes.py"
Cohesion: 0.18
Nodes (14): account_paths(), build_client(), FakeCloudClient, fixture, parametrize, Tests for token-free local account authentication adapters., test_account_email_rejects_unicode_line_separators(), test_logout_revokes_first_then_clears_locally_even_offline() (+6 more)

### Community 136 - "Design — Issue #223: reversible promotion and the seven-day initial lease"
Cohesion: 0.08
Nodes (23): 1. `src/ormah/config.py`, 2. `src/ormah/lifecycle.py`, 3. `src/ormah/models/node.py`, 4. `src/ormah/store/markdown.py`, 5. `src/ormah/index/schema.sql` and `src/ormah/index/db.py`, 5b. `src/ormah/index/builder.py` — amendment, 2026-08-18, 6. `src/ormah/engine/memory_engine.py`, 7. `src/ormah/background/consolidator.py` (+15 more)

### Community 137 - ".generate"
Cohesion: 0.13
Nodes (14): _capture_pgid(), _cleanup_persisted_stub(), _kill_group_or_proc(), HIGH-2/HIGH-1 (council-pr, Codex): signal a child's WHOLE process group by its…, SIGTERM the child's process group (stored pgid); fall back to per-PID…, SIGKILL the child's process group (stored pgid); fall back to per-PID kill()., Best-effort: delete the child's own transcript stub. Even with --no-session-…, Snapshot the child's process-group id AT SPAWN, while the leader is guaranteed… (+6 more)

### Community 138 - "duplicate_merger.py"
Cohesion: 0.13
Nodes (17): _composite_score(), _find_merge_candidates(), Detect near-duplicate memories and create merge proposals., Jaccard similarity on lowercased word sets., Weighted composite duplicate score., Find node pairs that might be duplicates. ``delta=False`` (default — agent…, Render one candidate pair for a batched duplicate prompt (#87)., Levenshtein-ratio similarity between two titles. Returns 0.0 if either is None. (+9 more)

### Community 139 - "test_cli_cloud_backup.py"
Cohesion: 0.10
Nodes (20): discard_prepared_cloud_restore(), Delete one unconsumed verified preparation without touching real backups., _cloud_status(), _local_status_service(), MemoryNode, Path, Snapshot ids are server-generated ULIDs, so newest is the lexical max. Listing…, RestoreClient (+12 more)

### Community 140 - "test_main_backfill_fallback.py"
Cohesion: 0.13
Nodes (20): fixture, Scheduler-independent embedding backfill fallback (#32, council C2/CH1/CH2).…, CH1: a second start while one is alive does not spawn a second thread., CH1: _stop_backfill_fallback stops a permanently-failing fallback., C1: se o join expira (encode travado), _stop retorna True e handle é mantido…, C1: quando o thread sai antes do timeout, _stop retorna False e handle é limpo., M-A: _stop_backfill_fallback must NOT return while the thread is alive.…, C2: fallback does not give up after 5 attempts — retries until success. (+12 more)

### Community 141 - "Whisper pipeline (involuntary recall)"
Cohesion: 0.13
Nodes (20): Whisper path, Whisper candidate diagnostics and retention, Flat markdown whisper formatter, Prompt intent classification, Selective query enhancement for follow-ups, Session prompt ring buffer, Topic-shift skip, Whisper pipeline (involuntary recall) (+12 more)

### Community 142 - "_FakeEngine"
Cohesion: 0.12
Nodes (16): _FakeEngine, Raw bytes >> cleaned chars. See 01-content-budget.md for why plain-text padding…, Records the char length of every content payload sent to ingestion., A flush that drains the whole closed delta (sub-cap) must not re-schedule —…, Review I-2: max_raw_bytes has to actually reach parse_transcript through…, Review I-2b: the SIBLING production leg -- SessionHandler._run_job ->…, Primary production trigger: an ACTIVE (non-idle) session with MULTIPLE closed…, An active session whose total closed content stays below flush_chars never gets… (+8 more)

### Community 143 - "auto_linker edge-write hardening — Overview"
Cohesion: 0.08
Nodes (19): auto_linker edge-write hardening — Overview, Background — what was diagnosed (2026-07-13), File structure, Setup (do this once, before Task 1), Task index, Verified facts that shape this plan (do not re-litigate), PR A — Idempotent edge writes (closes #117), Task 1: `_apply_edge` becomes idempotent (+11 more)

### Community 144 - "compute_affinity_boost"
Cohesion: 0.09
Nodes (25): batch_fetch_affinity(), compute_affinity_boost(), ndarray, Affinity boost module for the adaptive feedback loop. Computes per-node score…, Fetch all affinity rows for a list of node_ids in a single query. Returns a…, Compute the affinity boost for a candidate node. For each affinity row, a…, _insert_affinity_row(), _make_affinity_db() (+17 more)

### Community 145 - "test_backfill_embeddings.py"
Cohesion: 0.19
Nodes (16): Tests for MemoryEngine.backfill_embeddings (delta + schema-bump, no quarantine,…, A stop_event that is already set causes backfill to embed nothing., A stop_event that is never set does not interfere with normal completion., An interrupted schema pass must NOT advance embedding_schema_version., Fix B: an interrupted schema pass must NOT delete stale vectors. The DELETE is…, A node that always fails to encode stays genuinely missing (its stale vector is…, _set_schema_version(), _stored_version() (+8 more)

### Community 146 - "test_scoring_signals.py"
Cohesion: 0.08
Nodes (29): _lifecycle(), _make_node(), fixture, Tests for recency, access frequency, and tier scoring signals in hybrid search., A core node should outrank an archival node with the same base score., Boosts should not override a large relevance gap. RRF base scores are small…, Build a minimal node dict with scoring-relevant fields., Going from 0→5 accesses should give a larger boost than 15→20. (+21 more)

### Community 147 - "llm_generate"
Cohesion: 0.14
Nodes (19): llm_generate(), Maintenance path: swallow cancel/timeout to None (unchanged contract)., _bisect(), build_batch_prompt(), _diagnostic_pair_id(), _judge_chunk(), judge_pairs(), _judge_singles() (+11 more)

### Community 148 - "test_stats.py"
Cohesion: 0.09
Nodes (24): get, Request, Canonical stats API route., Canonical stats payload for tray, CLI, UI, and diagnostics., stats(), _log_decision(), _log_whisper(), fixture (+16 more)

### Community 149 - "entitlements.py"
Cohesion: 0.09
Nodes (40): _cached_entitlement(), Classify local entitlement state without network access during polling., AccountStatus, get_account_status(), Any, Return token-free account status using the canonical entitlement policy., _status_from_cache(), _as_utc() (+32 more)

### Community 150 - "visual.ts"
Cohesion: 0.23
Nodes (13): applyAppearance(), buildGraph(), NOTE: store the domain node type under `nodeType`, NOT `type` — sigma, seedPosition(), computeSelfRoles(), displayNodeSize(), edgeColor(), nodeLabel() (+5 more)

### Community 151 - "_find_link_candidates"
Cohesion: 0.18
Nodes (8): _find_link_candidates(), Find node pairs that need link classification. Returns up to *limit* pairs as…, test_find_candidates_uses_window_without_advancing(), Tests for the run_maintenance two-call protocol., Create n nodes with similar content and return their IDs., _seed_similar_nodes(), TestApplyMaintenanceResults, TestFindLinkCandidates

### Community 152 - "routes_ui.py"
Cohesion: 0.19
Nodes (14): get_graph(), get_insights(), get_node_detail(), get, Request, UI API routes for the web graph explorer., Search nodes for the UI, returning structured results. Uses the same hybrid…, Graph data for the explorer. Default (no ``space``): the *active graph* — non-… (+6 more)

### Community 153 - "conftest.py"
Cohesion: 0.16
Nodes (17): _clean_llm_cancel_epoch(), engine(), file_store(), _is_real_ormah_path(), _is_relative_to(), isolate_fastembed_cache(), _isolate_settings_from_global_env(), prevent_tests_mutating_real_ormah_install() (+9 more)

### Community 154 - "cmd_whisper_store"
Cohesion: 0.12
Nodes (20): cmd_whisper_store(), _drain_nudge_outbox(), _outbox_lock(), _queue_nudge(), Drop only this transcript's key; delete the file once it is empty (council…, Lock a STABLE file, never the outbox itself. flock locks an inode. The drain…, Append a boundary event durably and return its record id. Called BEFORE any…, Atomic rewrite. Caller MUST hold _outbox_lock(). (+12 more)

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

### Community 162 - "Database"
Cohesion: 0.08
Nodes (16): Database, Path, Insert one prompt payload shared by its candidate log rows., Run migrations for existing databases., Manages per-thread SQLite connections with WAL mode and serialized writes., Backfill content_fingerprint for rows whose file on disk hasn't changed. A row…, Add candidate-stage diagnostics without rebuilding feedback history., Record which synthetic pattern fired, so rot detection has a signal (#143). (+8 more)

### Community 163 - "compilerOptions"
Cohesion: 0.11
Nodes (17): compilerOptions, esModuleInterop, forceConsistentCasingInFileNames, lib, module, moduleResolution, noEmit, skipLibCheck (+9 more)

### Community 164 - "Review Relevance Is Not Confirmed Use — Implementation Plan"
Cohesion: 0.33
Nodes (5): After both tasks, File Structure, Global Constraints, Review Relevance Is Not Confirmed Use — Implementation Plan, Tasks

### Community 165 - "normalize_conflict_type"
Cohesion: 0.16
Nodes (16): _llm_classify_link(), Ask LLM to classify the relationship between two nodes. Returns a dict with…, normalize_conflict_type(), normalize_link_type(), Normalize LLM responses to canonical edge/conflict types., Map a raw LLM conflict type to a canonical value. Unknown values default to…, Map a raw LLM link type to a canonical value. Unknown values default to…, Tests for LLM response normalization functions. (+8 more)

### Community 166 - "test_llm_cancel.py"
Cohesion: 0.11
Nodes (15): Re-admit NEW calls after a RECOVERABLE cancel (the watcher's startup rollback).…, resume(), _clean_epoch(), fixture, Epoch semantics for LLM cancellation (ADR-0004 slice 2 redesign). These tests…, The watcher logs this count; it replaces the old "processes terminated" number., R4 regression. A resume() re-admits NEW calls; it must never un-cancel a call…, A final cancel must not outlive its lifespan: the llm_client adapter caches are… (+7 more)

### Community 167 - "_FakeEngine"
Cohesion: 0.17
Nodes (11): _FakeEngine, Blocks in backfill_embeddings until stop_event is set or 10s elapses. When…, Fix D: when the fallback thread survives the join timeout, engine.shutdown()…, Fix A: when scheduler shutdown does not complete in time, engine.shutdown()…, Positive path: both fallback and scheduler exit cleanly → engine.shutdown()…, council R1: with the always-on worker, start_session_watcher returns a non-…, test_engine_closed_when_both_exit_cleanly(), test_engine_not_closed_when_fallback_alive() (+3 more)

### Community 168 - "Review relevance is not confirmed use"
Cohesion: 0.15
Nodes (12): Accepted consequence — the legacy fallback, Blast radius, Related, Review relevance is not confirmed use, Scope, Tests, The defect, The fix (+4 more)

### Community 169 - "MaintenanceManager"
Cohesion: 0.19
Nodes (9): MaintenanceJob, MaintenanceManager, Any, Exception, In-memory state for a single maintenance run., Run maintenance phases in background threads with single-flight semantics., Start phase 1 if needed, or return the existing job state., Start phase 2 for the current prepared job. (+1 more)

### Community 170 - "_insert_node"
Cohesion: 0.19
Nodes (8): _insert_node(), When topical results survive, identity should still be included., identity-only intent with no search results should stay silent (no graph dump)., Reranker should only affect non-identity search results. Identity nodes are…, Identity results should be suppressed when no topical results survive., Low-scoring identity results should be suppressed when no topical results…, High-scoring identity results should survive even without topical results., TestWhisperIdentityGating

### Community 171 - "test_protection_routes.py"
Cohesion: 0.05
Nodes (24): Token-free result safe for the local API and product webview., RecoveryReadiness, embedding_backfill must be a registered admin task in the sleep-cycle (#32)., C1/I1: a failed task yields status=degraded AND HTTP 503 (not 200)., Happy path stays a plain dict (HTTP 200) with status=completed., test_run_all_tasks_completed_returns_dict_when_all_ok(), test_run_all_tasks_degraded_returns_503_when_a_task_raises(), FakeRecoveryKitService (+16 more)

### Community 172 - "detect_space_from_cwd"
Cohesion: 0.16
Nodes (19): detect_space_from_cwd(), detect_space_from_dir(), Shared space detection for CLI and MCP adapters., Detect the project space from an explicit directory path. Tries git repo…, Detect the project space from the current working directory. Tries git repo…, Resolve space: explicit flag > ORMAH_SPACE env > cwd detection., resolve_space(), Tests for shared space detection. (+11 more)

### Community 173 - "Changes"
Cohesion: 0.13
Nodes (14): 1. New module `src/ormah/lifecycle.py`, 2. `src/ormah/engine/memory_engine.py` — `_touch_access`, 3. `src/ormah/background/decay_manager.py`, 4. `src/ormah/config.py`, 5. Lifecycle-model version, Changes, Decision (from #191), Design — Issue #221: bound stability reinforcement and add a per-day cooldown (+6 more)

### Community 174 - "OllamaEmbeddingAdapter"
Cohesion: 0.25
Nodes (4): OllamaEmbeddingAdapter, ndarray, Produces embeddings via a local Ollama instance., TestOllamaAdapter

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

### Community 180 - "_claude_code_wire"
Cohesion: 0.18
Nodes (10): _claude_code_wire(), install_claude_agents(), install_claude_commands(), Install ormah custom agent definitions into ~/.claude/agents/., Install ormah slash command definitions into ~/.claude/commands/., A stale enabled flag must not cost the user the whisper., Deliberate: the CLI hooks are global and serve every other project., Fail-open: an unparseable config must not silently disable the whisper. (+2 more)

### Community 181 - "test_cloud_settings.py"
Cohesion: 0.20
Nodes (8): persist_settings_delta(), Persist only keys changed by a caller, serialized with every other writer., env_path(), fixture, test_account_and_protection_updates_are_serialized_without_lost_keys(), test_cloud_setting_does_not_change_runtime_when_persistence_fails(), test_cloud_setting_preserves_unrelated_env_lines_and_updates_runtime(), test_setup_delta_does_not_overwrite_a_concurrent_protection_setting()

### Community 182 - "stored_or_encoded"
Cohesion: 0.16
Nodes (16): embedding_text(), Canonical probe text for embeddings. Single source of truth: every vector in…, Build text for embedding. Truncates content to avoid topic averaging in long…, Return the stored embedding for *node_id*, re-encoding only if it is missing.…, stored_or_encoded(), _CountingEncoder, _ExplodingEncoder, Issue #88: pairwise jobs must reuse stored vectors, not re-encode probes. (+8 more)

### Community 183 - "match synthetic pattern"
Cohesion: 0.20
Nodes (5): match_synthetic_pattern(), The source of the pattern that matched, or None when the prompt is human.…, Which pattern fired — the signal rot detection needs (#143)., The empty regex matches everything and returns "" — falsy but REAL. Callers…, TestMatchSyntheticPattern

### Community 185 - "patch"
Cohesion: 0.03
Nodes (38): patch, _StopServerResult, configure_claude_hooks(), configure_codex_hooks(), generate_server_wrapper(), Write env dict to the global config file, preserving comments and ordering.…, Generate daemon wrapper with explicit, scoped API-key inheritance., Write Claude Code hook config to global settings using absolute paths. (+30 more)

### Community 186 - "test_memory_engine.py"
Cohesion: 0.05
Nodes (29): Shared wording for the agent-backed maintenance whisper signal., _generate_title(), Generate a short title from the first line/sentence of content., Tests for the memory engine., whisper fires onboarding nudge exactly once when identity is empty., Identity protection must be active on the production call path (I3)., Reranker unavailable (fresh install, model downloading) must degrade to…, Calling remember() without a title should auto-generate one from content. (+21 more)

### Community 187 - "TestConsolidationSignatureSkip"
Cohesion: 0.15
Nodes (5): An empty/blank summary is a no-op that must still record the signature., Invalid JSON is now treated as transient (mirrors raw is None): retry next run,…, The result-fallback recovers JSON shape but not the schema's enum constraint —…, The skip table is created by init_schema()'s executescript(schema.sql), which…, TestConsolidationSignatureSkip

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

### Community 195 - "_remove_claude_md_block"
Cohesion: 0.12
Nodes (12): _pi_unwire(), Remove a sentinel-wrapped markdown block from a target file., Remove the ormah instructions block from ~/.claude/CLAUDE.md., Remove the ormah instructions block from ~/.pi/agent/AGENTS.md., Remove the Ormah maintenance subagent from Pi's agent directory., _remove_claude_md_block(), _remove_markdown_block(), _remove_pi_agents() (+4 more)

### Community 196 - "_merge_hooks"
Cohesion: 0.23
Nodes (5): _install_hooks(), _merge_hooks(), Merge Ormah hook groups into an existing hooks dict, preserving co-tenants. For…, Read a JSON hooks config, merge Ormah hooks preserving co-tenants, write back.…, TestMergeHooks

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

### Community 202 - "routes_ingest.py"
Cohesion: 0.22
Nodes (13): ConversationLog, ingest_conversation(), ingest_file(), ingest_nudge(), NudgeRequest, BaseModel, post, Request (+5 more)

### Community 203 - "MemoryEngine"
Cohesion: 0.03
Nodes (66): get_encoder(), Get or create a cached embedding adapter. Args: settings: Application Settings…, is_maintenance_due_signal(), Return true for the current signal line and the legacy bare marker., apply_identity_space_invariants(), MemoryEngine, Any, datetime (+58 more)

### Community 204 - "FakeProtectionService"
Cohesion: 0.23
Nodes (3): FakeProtectionService, _operation(), ProtectionOperation

### Community 205 - "llm_errors.py"
Cohesion: 0.29
Nodes (6): LlmTimeoutError, Exception, Shared LLM adapter error types., The provider call exceeded its time budget. Distinct from a fast failure…, The maintenance path keeps its None-on-failure contract, so consolidator,…, test_llm_generate_swallows_cancel_and_timeout()

### Community 206 - "test_hippocampus.py"
Cohesion: 0.14
Nodes (16): _ingest_file(), Ingest a single file if its content has changed. Returns True if ingested., Return node_ids associated with a file via hippocampus state. Reads the…, Tests for the hippocampus file-watching & auto-ingestion layer., Same hash means the file is not re-ingested., Rapid writes result in a single ingestion call., hippocampus_enabled=False returns no observers., Ingesting a file records node_ids from created memories in state. (+8 more)

### Community 207 - "test_parser.py"
Cohesion: 0.14
Nodes (17): Tests for agent JSONL transcript normalization., A transcript whose RAW bytes dwarf its CLEANED conversation. Each turn carries…, The regression Amendment 3 exists to kill: tool-heavy turns must BATCH. Each…, A multi-turn slice's committed conversation stays within the budget — break…, The commit-site asymmetry: at the terminal-assistant site the budget check runs…, The progress guard: a lone turn bigger than the budget can't be shrunk, so it…, Tiny conversation, enormous raw span: the content budget is nowhere near full,…, A lone turn whose raw span exceeds the ceiling is committed anyway. Without… (+9 more)

### Community 208 - "Whisper: detect rotted synthetic-prompt patterns and propose corrections — Design"
Cohesion: 0.10
Nodes (20): 1. `whisper_health` is not a table — nothing persisted can be "re-contaminated", 2. The `Proposal` Pydantic model is dead code — there is nothing to "widen", 3. Absence from `retrieval_events` does not identify a filtered prompt, 4. The `ReviewQueue` UI exists and is orphaned, 5. "Matches zero" is the wrong rot criterion, Branch strategy, Component 1 — `match_synthetic_pattern()` (`src/ormah/engine/prompt_classifier.py`), Component 2 — record the match (`whisper_decisions`) (+12 more)

### Community 209 - "_remove_fastembed_cache"
Cohesion: 0.29
Nodes (5): get_model_cache_dirname(), Resolve a fastembed model name to its on-disk cache directory name., Delete the fastembed model cache entries that ormah downloaded., _remove_fastembed_cache(), TestRemoveFastembedCache

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
Cohesion: 0.11
Nodes (16): EmbeddingAdapter, ndarray, Abstract base class for embedding adapters., Interface that all embedding backends must implement., Encode a single text string to a normalized vector., Encode a batch of texts to normalized vectors., Encode a search query. Override to add model-specific query prefixes., Return the dimensionality of the embedding vectors. (+8 more)

### Community 218 - "Suppressing selection with a fact, not with the cursor (ADR-0004)"
Cohesion: 0.18
Nodes (10): Considered and rejected, Decision, Invariants, Residual risks, Selection suppression, Suppressing selection with a fact, not with the cursor (ADR-0004), Tests, The mechanism is a ratchet (+2 more)

### Community 219 - "strip_temporal_phrases"
Cohesion: 0.26
Nodes (4): Remove temporal phrases from *prompt*, returning the topical residue.…, strip_temporal_phrases(), Pure temporal queries should leave some residue (stop words)., TestStripTemporalPhrases

### Community 220 - "Design: ADR-0004 Fix A — stop dead-lettering `no_safe_boundary`"
Cohesion: 0.29
Nodes (6): Context, Decision, Design: ADR-0004 Fix A — stop dead-lettering `no_safe_boundary`, Risks / non-goals, Test changes, What does not change

### Community 221 - "VectorStore"
Cohesion: 0.09
Nodes (26): Any, ndarray, Serialize a numpy float32 vector to bytes for sqlite-vec., sqlite-vec backed vector storage., Insert or update a vector for a node. The DELETE + INSERT pair runs inside a…, Batch insert/update vectors in a single transaction., Find nearest neighbors. Returns results with cosine similarity scores., Retrieve the stored embedding for a node, or None if not found. (+18 more)

### Community 222 - "llm_cancel.py"
Cohesion: 0.14
Nodes (15): aborted(), begin_cancel(), begin_lifespan(), epoch_changed(), note_call_finished(), note_call_started(), Single authority for LLM call cancellation (ADR-0004 slice 2 redesign).…, Cancel the current epoch. Returns how many calls were in flight when it landed.… (+7 more)

### Community 223 - "test_miner.py"
Cohesion: 0.46
Nodes (12): _decision(), _log(), _make_db(), _node(), Path, Regression tests for the whisper eval miner. Build a temp SQLite DB with the…, _run_mine(), test_deterministic_truncation_keeps_injected_node() (+4 more)

### Community 224 - "Canonical Ormah guidance block (Claude memory file)"
Cohesion: 0.23
Nodes (12): Whisper eval case schema (memories, prompts, expectations), Six ormah_* Pi memory tools proxied to the HTTP API, Ormah-Pi extension (Pi coding agent memory layer), Pi transcript capture (compact/shutdown to POST /ingest/conversation), Pi whisper injection (POST /agent/whisper before each prompt), Ormah-Pi end-user setup playbook, Codex Ormah guidance block, maintenance_due whisper signal handling (+4 more)

### Community 225 - "transfer.py"
Cohesion: 0.23
Nodes (10): download_file(), put_file(), Path, Data-plane transfers for service-issued presigned URLs., Stream an encrypted bundle to a presigned object URL., Stream a presigned object download to disk., _validated_put_headers(), mock (+2 more)

### Community 226 - "should_rewind"
Cohesion: 0.19
Nodes (9): Gate the leading-orphan recovery on forward progress (ADR-0003, bug #149).…, should_rewind(), ADR-0003: rewind only on NO forward progress; an orphan-with-progress is…, The #149 byte pattern: end_turn boundary, then an assistant 'API Error' record…, A genuine legacy cursor parked mid-response: orphan AND no forward progress., No-progress alone (in-flight tail) must not rewind — only orphan+no-progress…, ADR-0003 large-orphan variant: a giant orphan fragment before the first user…, ADR-0003 accepted-loss pinning (council R1, Cursor+Codex): a GENUINE legacy… (+1 more)

### Community 227 - "TestWhisperDecisions"
Cohesion: 0.35
Nodes (3): Record a whisper call skipped because the prompt was machine-generated. Called…, Every whisper call writes exactly one whisper_decisions row (I10)., TestWhisperDecisions

### Community 228 - "_monkeypatch_run_embedding_backfill"
Cohesion: 0.22
Nodes (8): _monkeypatch_run_embedding_backfill(), _QuickEngine, Completes immediately with no missing nodes., Patch run_embedding_backfill to delegate to…, CRB: 8 threads racing _start_backfill_fallback must produce exactly 1 live…, CR1 reverted: handle is always cleared after stop, even on quick completion., test_concurrent_start_creates_single_thread(), test_stop_clears_handle()

### Community 229 - "Problemas de ingestão"
Cohesion: 0.10
Nodes (20): A conta do arquivo de 3,8 MB — corrigida após medição, A pergunta da madrugada — respondida, Como cada via fatia (são diferentes), Contabilidade de volume — de onde vêm os nós (7 dias), Direção de fix proposta — extração holística por bloco (André, 2026-07-17), FINDING — timeout do `SessionEnd`, corrigido após verificação, Issues a abrir, O erro que essa comparação corrigiu (+12 more)

### Community 230 - "recall_search_structured Keyword-Only Tuning Parameters — Implementation Plan"
Cohesion: 0.40
Nodes (4): Global Constraints, Out of scope, recall_search_structured Keyword-Only Tuning Parameters — Implementation Plan, Task 1: Keyword-only tuning parameters on `recall_search_structured`

### Community 231 - "TestWhisperSignal"
Cohesion: 0.29
Nodes (4): No signal when claude_maintenance_enabled=False., No signal when maintenance was run within the interval., Signal appears when no maintenance has ever been run., TestWhisperSignal

### Community 232 - "TestRecallFloorAndSpaceOrdering"
Cohesion: 0.30
Nodes (5): Deliberate recall: wider pool, space scores before the cut, relevance floor…, Cross-space noise penalized below the floor is dropped, not padded., A current-space match outside the old `limit` window survives the cut., A newer other-space node must NOT outrank an older current-space node., TestRecallFloorAndSpaceOrdering

### Community 233 - "_CancellableEngine"
Cohesion: 0.33
Nodes (4): _CancellableEngine, Loops checking stop_event; records whether it received it., stop_event is forwarded to the engine; handle is cleared; saw_stop is True., test_stop_cancels_long_backfill_within_join()

### Community 235 - "test_run_stats.py"
Cohesion: 0.16
Nodes (13): Issue #90: maintenance runs return a stats dict., At the 1440-minute defaults the nominal offsets (5/15/30/45) are unscaled —…, Issue #90 council R3 finding 2: scaling each job by ITS OWN interval let jobs…, Issue #90 council R2 finding 1: a DB/encoder failure inside the finder must not…, Same as above for duplicate_merger's finder (also only reachable via…, _spy_add_job(), test_auto_linker_returns_stats(), test_conflict_detector_stats_shape() (+5 more)

### Community 236 - "GraphView component (Cytoscape rendering + selection)"
Cohesion: 0.18
Nodes (11): AdminPanel (background task control via /admin/*), Edge opacity formula (max(0.2, weight or 0.5)), Graph appearance settings (localStorage ormah.graphAppearance.v1), GraphView component (Cytoscape rendering + selection), NodeDetail panel, Node sizing formula (24 + log2(access_count+1)*6), UI edge payload shape (source_id/target_id/edge_type/weight), /ui/graph data flow (load, filter client-side, node fetch, search) (+3 more)

### Community 237 - "test tool schemas"
Cohesion: 0.18
Nodes (5): get_openai_tools(), OpenAI function-calling schema adapter., Convert canonical tool schemas to OpenAI function-calling format., Canonical tool definitions shared across MCP and OpenAI adapters. TOOLS: The…, Focused tests for MCP-exposed tool schemas.

### Community 238 - "Spinner"
Cohesion: 0.13
Nodes (9): Thread-safe message change., Stop spinner and print [ok] final line., Background thread: render braille animation., Animated braille spinner with elapsed time display. Usage:: with…, Spinner, In non-TTY mode, Spinner prints [..] lines instead of animating., Updating with the same message shouldn't print again., Spinner cleans up even on exception. (+1 more)

### Community 239 - "relevance_quarantine.py"
Cohesion: 0.24
Nodes (10): iter_dropped(), prompt_version(), Path, quarantine_path(), Durable, append-only quarantine ledger for memories dropped by the relevance…, Path to the quarantine JSONL file, beside the store DB (settings.db_path)., First 12 hex chars of sha256 of the ingest LLM rules prompt text., Append one dropped-candidate record to the quarantine ledger. *mode* is… (+2 more)

### Community 240 - "updater.rs"
Cohesion: 0.17
Nodes (30): available_update(), available_update_store(), check(), check_desktop_update(), check_now(), concise_notes(), current_status(), desktop_update_status() (+22 more)

### Community 241 - "test_auto_linker.py"
Cohesion: 0.09
Nodes (30): Tests for LLM-based edge type classification in auto_linker., Pairs already checked should not trigger a second LLM call on re-run., Pairs classified as 'none' should be recorded in auto_link_checked., Re-writing a node's content bumps its seq to the head (crit#2 mechanism)., A direct metadata UPDATE (not via the builder) must not change seq., Updating a node's content should clear its checked pairs so it gets re-…, Issue #90: pairs_evaluated must reflect exactly one LLM decision call. Uses the…, Issue #90 (council finding 2): an LLM-unavailable pair (None decision) must… (+22 more)

### Community 242 - "client.py"
Cohesion: 0.14
Nodes (16): _client_version(), get_device_name(), get_or_create_device_id(), persist_account_credentials(), Path, HTTP client and local account identity for the Ormah Cloud service., Return this installation's stable UUIDv4, creating it with mode 0600., Human-readable name attached to server-side device tokens. (+8 more)

### Community 243 - "Session-watcher live-loss safety net — Implementation Plan"
Cohesion: 0.11
Nodes (13): Acceptance (issue #59), Branch, File map, Out of scope (YAGNI), Run tests with the working-tree interpreter, Session-watcher live-loss safety net — Implementation Plan, Tasks (do in order), Task 1: Config — reconcile interval + per-tick cap (+5 more)

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

### Community 250 - "2026-08-19-claude-cli-fixed-system-prompt/00-overview.md"
Cohesion: 0.13
Nodes (9): Council round 1 (2026-08-19) — findings folded in, Fixed --system-prompt in ClaudeCliAdapter — Implementation Plan, Global Constraints, Tasks (execute in order — Task 1 MUST precede any code edit), Task 1: Baseline legs — BEFORE any code change, Task 2: Fixed `_SYSTEM_PROMPT` constant in argv (TDD), Task 3: Per-call usage/cost log line (TDD), Task 4: AFTER legs + calibrated quality gate (+1 more)

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
Cohesion: 0.54
Nodes (8): /ormah:setup command, /ormah:status command, /ormah:upgrade command, Ormah Claude Code plugin (manifest, hooks, MCP, commands), Plugin first-run flow (install, setup, claude-md install), ormah claude-md install (scope-matched guidance block), Claude plugin setup playbook, ormah setup --skip-client-setup (plugin-safe setup contract)

### Community 258 - "HybridSearch"
Cohesion: 0.06
Nodes (37): _node_dict(), Convert a DB row to a plain node dict for candidate lists., HybridSearch, Combines FTS5 full-text search with sqlite-vec vector search., _make_node(), Unit tests for HybridSearch title boost score capping. Verifies that…, Multiple query tokens matching title → high title_bonus, but still capped., Even with tier boost + recency + access, final_score capped at 1.0. (+29 more)

### Community 259 - "_create_pair"
Cohesion: 0.13
Nodes (19): _apply_edge(), Record a link decision: write to auto_link_checked and optionally create an…, _create_pair(), Helper: create two similar nodes without auto-linking, return their IDs., A concurrent writer created the same edge between collection and apply.…, The winner of the race already wrote its Connection to the file. We must not…, The winner committed the DB row but crashed before saving its markdown. The…, An INSERT OR IGNORE that inserted nothing is not a creation. Counting it as one… (+11 more)

### Community 260 - "Avaliação profunda — ormah Beta (`local-main`) — 2026-07-13"
Cohesion: 0.11
Nodes (17): 10. Riscos & não verificado, 1. Sumário executivo, 2. Estado vivo do Beta (snapshot), 3. Arquitetura & código — verdictos dos hotspots, 4. Testes & operações, 5. Tecnologia — manter × trocar (pesquisa 2025-2026, com fontes), 6. Produto de memória — onde o valor vaza, 7.1 Log de produção contaminado por processos de teste — **[V mecanismo]** (+9 more)

### Community 261 - "Path"
Cohesion: 0.06
Nodes (32): _candidate_project_roots(), _codex_agents_target(), _detect_claude_plugin_scope(), _enabled_plugin_keys(), _get_claude_md_target(), _get_running_server_data_dir(), _hooks_manifest_wires_ormah(), install_claude_md() (+24 more)

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

### Community 271 - "_legacy_archival"
Cohesion: 0.57
Nodes (6): _legacy_archival(), _meta_done(), A node whose FILE lacks archived_at (remember(tier=archival) never stamps it)., test_backfill_skipped_when_disabled(), test_backfill_stamps_legacy_files_and_survives_rebuild(), test_backfill_write_failure_preserves_file_and_retries()

### Community 272 - "Separate Surfaced Results from Confirmed Memory Use — Design"
Cohesion: 0.11
Nodes (17): 1. Problem, 2. What is already correct on `upstream/main`, 3. The actual defect, in four points, 4.1 Task A — subtraction, 4.2.1 Serializing the mutator, 4.2 Task B — addition, 4.3.1 The delivery contract is at-most-once, 4.3 Concurrency: the reinforcement runs outside the transaction (+9 more)

### Community 273 - "Whisper golden corpus (golden/golden.jsonl, local-only)"
Cohesion: 0.50
Nodes (5): Case-design rules (labels precede runs, >=6 memories, named distractors), Whisper golden corpus (golden/golden.jsonl, local-only), Mined provisional cases (ormah eval whisper mine), Whisper F1 baselines table (2026-07-03), Maintenance decision rules (honest none, submit all evaluated pairs)

### Community 276 - "_load_state"
Cohesion: 0.19
Nodes (14): _load_state(), Scan a directory for new/changed .md files. Returns count of files ingested., One-shot scan of all watch dirs (for admin trigger / manual catch-up)., Load persisted state for a watch directory., run_hippocampus_scan(), _scan_directory(), Only .md files are picked up by scan., run_hippocampus_scan ingests files from configured dirs. (+6 more)

### Community 277 - "build"
Cohesion: 0.47
Nodes (5): App, build(), Result, server_status_label(), server_toggle_label()

### Community 278 - "verify release versions"
Cohesion: 0.73
Nodes (5): main(), Path, _read_plugin_version(), _read_project_version(), verify_release_versions()

### Community 279 - "files"
Cohesion: 0.33
Nodes (6): files, ormah-pi.ts, src, pi, extensions, agents

### Community 280 - "install_pi_md"
Cohesion: 0.21
Nodes (7): install_pi_agents(), install_pi_md(), _pi_wire(), Install ormah instructions into Pi's AGENTS.md (global or project)., Install the Ormah maintenance subagent prompt into Pi's agent directory., TestInstallPiAgents, TestInstallPiMd

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

### Community 340 - "test_soft_delete_tombstone.py"
Cohesion: 0.73
Nodes (5): _make(), _store(), test_list_deleted_returns_id_and_deleted_at(), test_purge_removes_tombstone(), test_soft_delete_stamps_deleted_at()

### Community 341 - "ingest-deferred-tracks.md"
Cohesion: 0.18
Nodes (8): Amendment 2026-07-20 — ship in SHADOW mode, not drop-on-by-default, Amendment 2026-07-21 — lean the rollout: runtime flag, no code guard, best-effort ledger, Consequences, Considered options, The relevance gate is a provenance label the Extractor emits and code drops — no per-user calibration, Dissolved, How this ledger stays alive, Ingest — deferred tracks ledger

### Community 342 - "Auditoria do ADR-0004 — 2026-08-09"
Cohesion: 0.14
Nodes (13): 4.1 Declara como *shipped* algo que nunca foi mesclado, 4.2 A premissa está falsificada pela medição de hoje, 4.3 A cascata — porque o defeito "muda de lugar a cada council-pr", 4.4 A resposta certa já estava escrita no próprio ADR, Auditoria do ADR-0004 — 2026-08-09, O que NÃO foi verificado, Parte 1 — Decisão original (nudge, cursor no servidor, worker sempre-ligado): **CORRETA**, Parte 2 — Amendment 2026-07-22 (spool de diretório): **CORRETO, e exemplar** (+5 more)

### Community 343 - "beta-keep (150 commits) — MUST survive the Task 6 merge (not in any PR, not upstream)"
Cohesion: 0.14
Nodes (13): base-status (I2), beta-keep (150 commits) — MUST survive the Task 6 merge (not in any PR, not upstream), chore/style (4), config (2), dedup/maintenance (17), delta-manifest — Beta-only commits classification (Task 1, 2026-07-10), docs (19), index/rebuild (3) (+5 more)

### Community 345 - "Spec — isolate `test_setup.py` from the developer's machine"
Cohesion: 0.14
Nodes (13): 1. `tests/conftest.py` — autouse fixture `_reset_settings_singleton`, 2. `tests/test_setup.py` — patch the real seam, B — the `Settings` singleton outlives test isolation (3 tests), C — `_find_binary` outflanks the mock (3 tests), Design, Evidence, Non-goals, Problem (+5 more)

### Community 346 - "LoggingHandler"
Cohesion: 0.23
Nodes (7): Lock, LoggingHandler, main(), poll_disk_truth(), Event, FileSystemEventHandler, Path

### Community 347 - "Draft comment for #209 — failure-mode analysis of the four-way duplicate policy"
Cohesion: 0.14
Nodes (13): 0. Baseline: what "clear duplicate" means operationally today, 1. Wrong auto-merge of near-duplicates (case 1 misfires), 2. Contradiction misclassified as duplicate (the case 3 / case 1 boundary), 3. Undo is asymmetric: the kept node is unrecoverable (undo fidelity, part 1), 4. Undo fidelity after downstream edits (undo fidelity, part 2), 5. Proposal invalidation races on merge/delete (agreed mechanic, not yet built), 6. Queue re-growth and starvation under "leave both alone, reconsider later" (case 2), 7. Interaction with #223's promotion path (active-only candidacy) (+5 more)

### Community 348 - "run_whisper_log_cleanup"
Cohesion: 0.24
Nodes (10): datetime, Bounded retention for high-volume whisper candidate diagnostics., Delete one bounded batch of stale, unreferenced rejected candidates. Injected…, run_whisper_log_cleanup(), _event(), Tests for normalized whisper payload retention., test_cleanup_deletes_only_stale_unreferenced_rejections(), test_cleanup_is_bounded_and_idempotent() (+2 more)

### Community 349 - "TestStopOffsetCeiling"
Cohesion: 0.20
Nodes (7): ADR-0004 Task 3: ``stop_offset`` is an ABSOLUTE hard ceiling — no turn is…, Byte offset after the first ``upto`` records, matching ``_write_jsonl``'s…, The flagged leak: ``max_conversation_chars`` commits an oversized FIRST turn…, Everything closed at or before the ceiling is committed; the first turn that…, The non-nudge lane passes ``stop_offset=None`` and must parse exactly as before., The ceiling must also clamp the Codex ``task_complete`` closure site, not only…, TestStopOffsetCeiling

### Community 350 - "TestMarkOutdated"
Cohesion: 0.15
Nodes (6): feedback_engine(), fixture, Tests for the mark_outdated feedback tool., Engine with a node to give feedback on., An outdated memory should get a lower score in search., TestMarkOutdated

### Community 351 - "Port #221 (bounded reinforcement) onto local-main's post-#220 API — Implementation Plan"
Cohesion: 0.29
Nodes (6): Baseline, File Structure, Final Gate, Global Constraints, Port #221 (bounded reinforcement) onto local-main's post-#220 API — Implementation Plan, Task Order

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

### Community 356 - "LocalAdapter"
Cohesion: 0.24
Nodes (4): LocalAdapter, ndarray, Wraps fastembed with lazy loading and caching., TestLocalAdapter

### Community 357 - "_edges_between"
Cohesion: 0.14
Nodes (14): _edges_between(), LLM returns None -> no edge created (no heuristic fallback)., With llm_provider='none', LLM is never called and no edges are created., Return all edges between two nodes., Malformed LLM JSON → recorded as result='error' (no edge), so the node resolves., LLM classifies as supports -> edge created with type supports., LLM classifies as contradicts -> edge created with type contradicts., LLM classifies as none -> no edge created. (+6 more)

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

### Community 363 - "get_ormah_bin_path"
Cohesion: 0.11
Nodes (13): get_ormah_bin_path(), Find the absolute path to the ormah binary., _claude_desktop_wire(), configure_claude_code_mcp(), configure_claude_desktop(), _merge_json_file(), Read a JSON file, deep-merge updates, and write back., Register ormah MCP server in Claude Code user config. Uses ``claude mcp add``… (+5 more)

### Community 364 - "TestWhisperDebugMode"
Cohesion: 0.23
Nodes (6): _make_node(), mock_graph(), fixture, Tests for _return_debug mode on build_whisper_context., Nodes that don't clear the injection gate should not appear in injected_ids., TestWhisperDebugMode

### Community 365 - "run_consolidation"
Cohesion: 0.09
Nodes (19): _find_consolidation_clusters(), Find clusters of similar working memories and consolidate via LLM., Find clusters of similar working-tier nodes for consolidation. Returns up to…, run_consolidation(), Return pending maintenance work for Claude-in-the-loop processing. Phase 1 of…, consolidation_engine(), fixture, Tests for the memory consolidation background job. (+11 more)

### Community 366 - "Investigação — pipeline de whisper — 2026-07-15"
Cohesion: 0.17
Nodes (11): Como funciona (pipeline), DEVE (defeitos e desperdício verificados), Investigação — pipeline de whisper — 2026-07-15, Números medidos (banco vivo, 30 dias, 2026-07-15), O que está bom (não mexer), O que é, PODE (custo/manutenção), PRECISA (confiabilidade/observabilidade) (+3 more)

### Community 367 - "Setup: stop clobbering pre-existing user config"
Cohesion: 0.17
Nodes (11): 1. `_is_ormah_hook` — single source of truth (existing), 2. `_merge_hooks(existing_hooks: dict, ormah_hooks: dict) -> dict` (new), 3. `configure_claude_hooks` / `configure_codex_hooks` (changed), 4. `_write_env_file(env: dict[str, str])` (changed; signature unchanged), Design, Goals, Non-goals, Problem (+3 more)

### Community 368 - "LLM Cancellation Redesign — Single Global Epoch"
Cohesion: 0.17
Nodes (11): Acceptance criteria, Consequences, Known risks, LLM Cancellation Redesign — Single Global Epoch, Out of scope, Ownership: who cancels, and when, The adapter becomes a pure epoch consumer, The design (+3 more)

### Community 369 - "Path"
Cohesion: 0.29
Nodes (6): HippocampusHandler, FileSystemEventHandler, Path, Watches for .md file create/modify events with debouncing., Schedule a debounced ingestion for the given file., Actually ingest the file (called after debounce).

### Community 370 - "2026-08-19-claude-cli-stable-cache-prefix/00-overview.md"
Cohesion: 0.07
Nodes (20): Global Constraints, Stable cache prefix for `ClaudeCliAdapter` — Implementation Plan, Tasks (execute in order — Tasks 1 and 2 MUST precede any code edit), Test design — why there are no substring assertions, The system prompt constant — a correction to the spec, Task 1: Close the hot-reload precondition, Task 2: BEFORE round — the three judges on current code, Task 4: Per-call usage/cost log line (TDD) (+12 more)

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
Cohesion: 0.18
Nodes (10): Evidence gate — the Beta's data describes `local-main`, never `upstream/main`, Fork & contribution workflow (Ormah), Golden rules, Import gate — run it before trusting any test number from an island, Mental model (the one thing that prevents every problem), Recipe A — contribute a change upstream, Recipe B — also run the change in your Beta right now, Recipe C — sync down (upstream advanced / your PR landed) (+2 more)

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

### Community 389 - "Design — remove the wall-clock race from `test_hippocampus.py`"
Cohesion: 0.18
Nodes (10): Approach, Call sites, Component, Design — remove the wall-clock race from `test_hippocampus.py`, Error handling, Out of scope, Problem, Root cause (+2 more)

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

### Community 424 - "Issue #232 — Explicit filter parameters on the recall boundary"
Cohesion: 0.15
Nodes (12): Approach, Body, Design, Error handling, Issue #232 — Explicit filter parameters on the recall boundary, Out of scope, Problem, Severity: the typo is latent, not active (+4 more)

### Community 425 - "config.py"
Cohesion: 0.10
Nodes (19): model_validator, _deprecated_key_present(), Path, Application configuration via environment variables and .env file., True when the deprecated key is set in ANY configured settings source.…, _ingest_adapter_baseline_timeout(), _prompt_exceeds_provider_capacity(), The timeout the ACTIVE ingest adapter would use on its own. Adapters treat… (+11 more)

### Community 427 - "hippocampus.py"
Cohesion: 0.20
Nodes (9): _detect_space(), _file_hash(), _matches_ignore(), Hippocampus — real-time file watching & auto-ingestion of .md files., Detect the project space from a file path. Tries git repo basename first, falls…, Return SHA-256 hex digest of a file's contents., Return True if rel_path matches any of the ignore patterns. Supports ``**``…, Git repo path produces correct space name. (+1 more)

### Community 428 - "Problema 3 — o churn de `seq` (refutado como causa do backlog)"
Cohesion: 0.40
Nodes (5): A cadeia de código (confirmada, elo a elo), Conclusão, Estado atual (12:35 -03, Agente 5), Por que a cadeia não explica o backlog, Problema 3 — o churn de `seq` (refutado como causa do backlog)

### Community 429 - "Task 3 — Pure helpers: `buildSpaceLegend` + `scopeLabel`"
Cohesion: 0.40
Nodes (4): 3a. `buildSpaceLegend`, 3b. `scopeLabel`, 3c. `createRequestGuard` (F2 — race de reload), Task 3 — Pure helpers: `buildSpaceLegend` + `scopeLabel`

### Community 430 - "Bounded Stability Reinforcement (#221) — Implementation Plan"
Cohesion: 0.25
Nodes (7): Acceptance Criteria → Task Map, Bounded Stability Reinforcement (#221) — Implementation Plan, File Structure, Final Gate (after Task 6), Global Constraints, Setup (once, before Task 1), Task Order

### Community 431 - "LiteLLMEmbeddingAdapter"
Cohesion: 0.21
Nodes (5): LiteLLMEmbeddingAdapter, ndarray, Produces embeddings via litellm.embedding()., Tests for embedding adapters and the provider registry., TestLiteLLMAdapter

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

### Community 553 - "start_hippocampus"
Cohesion: 0.28
Nodes (9): Observer, Start file watchers for all configured hippocampus directories. Performs an…, Stop and join all hippocampus observers., start_hippocampus(), stop_hippocampus(), Files present before watcher starts get ingested on catch-up scan., A file created after watcher starts gets ingested., test_initial_scan_ingests_existing_files() (+1 more)

### Community 555 - "_commit_updates_chunked"
Cohesion: 0.31
Nodes (6): _commit_updates_chunked(), Apply (importance, node_id) updates in bounded write transactions so a full-…, The all-nodes write in importance_scorer must commit in bounded chunks., _RecordingDB, test_commit_updates_chunked_empty(), test_commit_updates_chunked_splits_into_batches()

### Community 556 - "init_key"
Cohesion: 0.07
Nodes (68): identity_to_str(), _atomic_write_0600(), CloudKeyError, current_recipient(), _ensure_recovery_kit_can_be_rewritten(), extract_store_id(), extract_store_id_from_text(), import_key() (+60 more)

### Community 559 - "test_hybrid_search_raw_cosine.py"
Cohesion: 0.33
Nodes (6): _make_hybrid(), _make_node(), Unit tests for the raw_cosine absolute-signal contract in HybridSearch. The…, A node found only via FTS (no vector hit) must carry no raw_cosine., A node with a genuine vector measurement keeps its raw_cosine., TestRawCosineContract

### Community 561 - "test_index_embedding_retry.py"
Cohesion: 0.29
Nodes (5): _FlakyEncoder, Tests for _index_embedding bounded retry (#32)., Fails `fail_times` then succeeds, returning a fixed-dim vector., test_index_embedding_gives_up_without_raising(), test_index_embedding_retries_then_succeeds()

### Community 563 - "test_migration_seq.py"
Cohesion: 0.33
Nodes (5): Tests for nodes.seq column migration and backfill., Regression: a pre-seq DB must migrate without 'no such column: seq'.…, Existing nodes get a monotonic seq ordered by created ASC., test_init_schema_migrates_legacy_db_without_seq(), test_seq_column_backfilled_by_created()

### Community 564 - "db.py"
Cohesion: 0.13
Nodes (13): Vector storage and search using sqlite-vec., SQLite database connection management., _init_db(), Concurrency tests for the thread-local Database connection model., Regression: vec0 module is loaded per connection; a fresh thread must still be…, A read on thread B returns promptly while thread A holds a write tx., test_each_thread_gets_distinct_connection(), test_read_during_write_does_not_block() (+5 more)

### Community 574 - "_save_state"
Cohesion: 0.50
Nodes (4): Persist state for a watch directory., _save_state(), State file survives across load/save cycles., test_state_file_persists()

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
- **1348 isolated node(s):** `Task 2: BEFORE round — the three judges on current code`, `Task 4: Per-call usage/cost log line (TDD)`, `Task 6: Full verification and live measurement`, `Phase`, `AgentInfo` (+1343 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **143 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

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
- **Why does `MemoryEngine` connect `MemoryEngine` to `test_session_watcher.py`, `HybridSearch`, `main.py`, `run_eval`, `memory_engine.py`, `session_watcher.py`, `test_scoring_signals.py`, `Settings`, `_load_state`, `start_session_watcher`, `test_claude_cli_adapter.py`, `test_stats.py`, `conftest.py`, `SessionHandler`, `test_session_watcher_flush.py`, `NodeType`, `JobTracker`, `Database`, `IndexBuilder`, `test_confirmed_use_contract.py`, `start_hippocampus`, `MaintenanceManager`, `hippocampus.py`, `config.py`, `GraphIndex`, `ContextBuilder`, `test_ingest_extraction.py`, `FileStore`, `test_memory_engine.py`, `ProtectionOperationKind`, `TestClient`, `test cleanup auto ingested`, `ConnectRequest`, `test_hippocampus.py`, `FastAPI`, `get_fastembed_cache_dir`, `recall/cli.py`, `run_whisper_log_cleanup`, `VectorStore`, `TestSubmitFeedbackBasic`, `test relevance runner`, `TestWhisperDecisions`, `run_whisper_eval`, `start_scheduler`, `whisper/cli.py`, `TierManager`, `run_consolidation`, `CreateNodeRequest`, `seed_case`, `Path`, `test_backup.py`, `seed_case`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._