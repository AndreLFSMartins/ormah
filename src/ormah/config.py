"""Application configuration via environment variables and .env file."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

_DEPRECATED_FLUSH_BYTES_ENV = "ORMAH_SESSION_WATCHER_FLUSH_BYTES"
_warned_flush_bytes = False


_ENV_FILES = [
    Path.home() / ".config" / "ormah" / ".env",  # Fixed global config
    Path(".env"),  # Local override (cwd)
]
# pydantic-settings reads later files with higher priority
_EXISTING_ENV_FILES = [str(p) for p in _ENV_FILES if p.exists()]


def _deprecated_key_present(env_files: list[str] | None = None) -> bool:
    """True when the deprecated key is set in ANY configured settings source.

    pydantic-settings resolves the process environment AND the .env files in _ENV_FILES, so
    checking os.environ alone would miss the likeliest case: an operator who wrote the old key
    into ~/.config/ormah/.env. Parsing is deliberately crude -- we only need presence, never the
    value (the value is in the wrong unit and is discarded either way).
    """
    if _DEPRECATED_FLUSH_BYTES_ENV in os.environ:
        return True
    # Mirror Settings' own resolution, including the `or ".env"` fallback (config.py:20) -- a
    # scanner that reads a different list than Settings does would report on files nobody loads
    # (council R2, Cursor).
    sources = env_files if env_files is not None else (_EXISTING_ENV_FILES or [".env"])
    for path in sources:
        try:
            text = Path(path).read_text()
        except FileNotFoundError:
            # A fresh install has no ~/.config/ormah/.env and no ./.env: _EXISTING_ENV_FILES is
            # then empty and the `or [".env"]` fallback names a file nobody created. That is
            # "nothing to scan", not a config-read failure -- warning here would fire on every
            # `Settings()` on a clean machine (review F1).
            continue
        except (OSError, UnicodeDecodeError) as e:
            # Council decision (repo owner): swallowing this silently hides a real config-read
            # failure from the operator -- exactly the class of silent surprise this whole
            # deprecation path exists to prevent. Warn, then keep scanning the other sources.
            # UnicodeDecodeError is included: a non-UTF-8 .env would otherwise escape this
            # helper (called from a model validator) and turn a cosmetic deprecation scan into
            # a hard config-load failure (review M-11).
            logger.warning("Could not read %s while scanning for the deprecated flush-bytes key: %s", path, e)
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.split("=", 1)[0].strip().upper() == _DEPRECATED_FLUSH_BYTES_ENV:
                return True
    return False


class Settings(BaseSettings):
    model_config = {"env_prefix": "ORMAH_", "env_file": _EXISTING_ENV_FILES or ".env", "extra": "ignore"}

    # Server
    host: str = "127.0.0.1"
    port: int = 8787
    log_format: str = "text"  # "text" or "json"
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # Paths
    memory_dir: Path = Path.home() / ".local" / "share" / "ormah" / "memory"

    # Local memory backups. Only source-of-truth memory files are backed up;
    # SQLite/vector indexes are derived and rebuilt after restore.
    backup_enabled: bool = True
    backup_dir: Path = Path.home() / ".local" / "share" / "ormah" / "backups"
    backup_interval_hours: int = 24
    backup_retention_count: int = 10

    # Encrypted cloud backups (paid tier). Client-side keys; nothing readable
    # ever leaves the machine. Off by default until an account is configured.
    cloud_backup_enabled: bool = False
    cloud_backup_interval_hours: int = 24
    cloud_api_url: str = "https://api.ormah.me"
    account_token: str | None = None
    account_email: str | None = None

    # Embeddings
    embedding_provider: str = "local"  # "local", "ollama", "litellm"
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = 768
    # Set to the NEW dim to authorize ONE deliberate destructive reindex of a
    # populated vector store (embedding-model migration). Remove after the boot.
    reindex_on_dim_change: int = 0

    # LLM for extraction. Disabled by default; setup can opt into cloud/local providers.
    llm_provider: str = "none"
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_base_url: str = "http://localhost:11434"
    llm_timeout_seconds: int = 60
    llm_num_predict: int = 4096
    ollama_num_ctx: int = 65536   # INPUT window; never inherit the server default (silent truncation)
    llm_api_key_env_var: str | None = None
    llm_inherit_api_key: bool = False

    # Ingest (server-side extraction) LLM override. Empty falls back to llm_provider/llm_model.
    ingest_llm_provider: str = ""
    ingest_llm_model: str = ""
    claude_cli_timeout_seconds: int = 120
    claude_cli_bin: str | None = None
    claude_cli_max_concurrency: int = 1

    # Background intervals (LLM-dependent tasks default to daily to keep costs low)
    auto_link_interval_minutes: int = 1440
    decay_interval_hours: int = 24
    conflict_check_interval_minutes: int = 1440
    conflict_check_all_spaces: bool = False
    duplicate_check_interval_minutes: int = 1440
    auto_cluster_interval_minutes: int = 60
    reinforcement_retry_interval_minutes: int = 60

    # Embedding backfill / vector-store reconciliation (#32).
    # Set the interval to a very large value (e.g. 999999) to disable the
    # in-process recurring job and let the 02:00 sleep-cycle (run-all) drive it.
    embedding_backfill_interval_minutes: int = 60
    embedding_index_max_retries: int = 2
    embedding_index_retry_backoff_seconds: float = 0.5

    # Hippocampus (file watching & auto-ingestion)
    hippocampus_watch_dirs: list[Path] = []
    hippocampus_debounce_seconds: float = 2.0
    hippocampus_enabled: bool = True
    hippocampus_ignore_patterns: list[str] = []

    # Session watcher (auto-ingest agent transcripts; default path is Claude Code)
    session_watcher_enabled: bool = False
    session_watcher_dir: Path = Path("~/.claude/projects")
    session_watcher_debounce_seconds: float = 60.0
    session_watcher_min_turns: int = 5
    session_watcher_lookback_hours: int = 72
    session_watcher_idle_threshold: float = 600.0  # was 30.0 — 30s flushed 1-turn batches
    session_watcher_retry_seconds: float = 30.0    # FSEvents-miss retry — decoupled from idle
    session_watcher_flush_chars: int = 60000       # CONVERSATION chars that close a Batch (~15K tok)
    # Independent raw-span budget (ADR-0001 Am.3). Measured p99 of the realised raw span under the
    # 60000-char content budget: 9,844,378 B over 420 slices from the 200 largest live transcripts
    # (2026-07-26, scripts/measure_ingest_budget.py --budget 60000 --files 200). Rounded up to 10 MB.
    # p99 deliberately, not the median: this bounds pathological cost. At 10 MB it WOULD HAVE BOUND
    # on 4/420 (0.95%) of large-file slices and 4/2562 (0.16%) corpus-wide. That is the pre-ceiling
    # distribution -- the replay never passed max_raw_bytes -- so the realised rate once the ceiling
    # is live is somewhat higher: each oversized span is re-sliced into several ceiling-closed ones
    # (the 40.3 MB outlier alone becomes >= 4). Still a tail bound, not a second budget competing
    # with the content budget.
    session_watcher_max_raw_bytes: int | None = 10_000_000
    session_watcher_reconcile_interval_minutes: int = 5
    session_watcher_reconcile_max_per_tick: int = 50
    session_watcher_reconcile_max_seconds: float = 30.0
    session_watcher_catchup_concurrency: int = 1

    # Tier limits
    core_memory_cap: int = 50
    working_decay_days: int = 14  # Deprecated: superseded by FSRS-based decay

    # FSRS spaced repetition decay
    fsrs_initial_stability: float = 5.814   # days; -7 / ln(0.3) — a seven-day unused lease
    fsrs_decay_threshold: float = 0.3      # R below this = decay candidate
    fsrs_max_stability: float = 365.0      # cap at 1 year

    # Bounded reinforcement (#221). See docs/12 for the curve.
    fsrs_growth_factor: float = 0.5        # g; size of one reinforcement step
    fsrs_growth_exponent: float = 0.5      # w; damps the step as stability rises
    fsrs_spacing_cap: float = 2.0          # ceiling on the R^-0.2 spacing factor
    fsrs_reinforcement_cooldown_days: float = 1.0  # min days between numeric updates

    # Search
    fts_weight: float = 0.4
    vector_weight: float = 0.6
    similarity_threshold: float = 0.4
    rrf_k: int = 60

    # Embedding truncation
    embedding_max_content_chars: int = 512

    # Score blending
    similarity_blend_weight: float = 0.5
    fts_only_dampening: float = 0.5
    min_result_score: float = 0.1
    rrf_min_spread_ratio: float = 0.05

    # Question query adjustments
    question_fts_weight_scale: float = 0.3
    question_vector_weight_scale: float = 1.5
    question_similarity_blend_weight: float = 0.85

    # Title and length scoring
    title_match_boost: float = 2.0  # Multiplicative bonus for query terms in title (0 = disabled)
    length_penalty_threshold: int = 300  # Content length above which vector similarity is penalized

    # Scoring signals
    recency_boost: float = 0.05
    recency_half_life_days: float = 7.0
    access_boost: float = 0.05
    tier_boost_core: float = 0.1
    tier_boost_working: float = 0.0
    tier_boost_archival: float = -0.1

    # Spreading activation
    activation_decay: float = 0.5
    activation_seed_count: int = 5
    activation_max_per_seed: int = 3

    # Auto-link
    auto_link_similarity_threshold: float = 0.65
    auto_link_cross_space_penalty: float = 0.1  # subtracted from similarity for cross-space pairs
    auto_link_max_edges_per_run: int = 500
    auto_link_max_nodes_per_run: int = 500  # cursor batch: nodes scanned per run
    duplicate_check_max_nodes_per_run: int = 500  # seed batch per dedup run (#81)
    conflict_check_max_nodes_per_run: int = 500   # seed batch per conflict run (#81)

    # Pairwise-maintenance batching (#87). K=1 keeps today's single-pair flow;
    # operators on per-call-expensive providers raise K (10-16). Per-job
    # overrides (0 = use the global K) let one job batch while others stay
    # single — the A/B eval gate is per job (council C3).
    maintenance_pairs_per_call: int = 1
    auto_link_pairs_per_call: int = 0
    duplicate_check_pairs_per_call: int = 0
    conflict_check_pairs_per_call: int = 0
    maintenance_timeout_per_pair_seconds: int = 10
    # Per-run caps, denominated in PAIRS EVALUATED (not LLM calls). Defaults
    # preserve CURRENT behavior exactly (council I1): 0 = no extra bound
    # (auto_link/dedup today), conflict keeps its existing 10000 candidate
    # bound. Raising these is an explicit operator/config decision, not part
    # of this PR.
    auto_link_max_pairs_per_run: int = 0
    duplicate_check_max_pairs_per_run: int = 0
    conflict_check_max_pairs_per_run: int = 10000

    # Auto-merge
    auto_merge_threshold: float = 0.85

    # Bounded forgetting (#28). Master switch OFF by default — deletion is
    # irreversible, so it must be armed explicitly via ORMAH_DELETION_ENABLED.
    deletion_enabled: bool = False
    forgetting_interval_hours: int = 24
    deletion_min_archival_days: int = 90       # graveyard age before eligible
    deletion_retrievability_floor: float = 0.05  # FSRS R must be below this
    deletion_max_degree: int = 2               # only weakly-connected leaves
    deletion_strong_edge_weight: float = 0.7   # any edge >= this protects the node
    deletion_retention_days: int = 30          # soft-delete reversibility window
    archival_soft_cap: int = 0                 # 0 = disabled; >0 = evict worst-first to cap


    # Importance scoring weights (3 dynamic signals)
    importance_access_weight: float = 0.34
    importance_edge_weight: float = 0.33
    importance_recency_weight: float = 0.33
    importance_recompute_interval_minutes: int = 120

    # Importance: absolute normalization references
    importance_access_reference: int = 50
    importance_edge_reference: int = 20

    # Importance: recency half-life (separate from search recency)
    importance_recency_half_life_days: float = 14.0

    # Decay gate removed in #222: working->archival now depends on retrievability
    # alone, because cumulative access and edge counts could push importance
    # permanently above any threshold. Kept because it is a documented setting;
    # bounded forgetting (#28/#31) reintroduces a reader as the deletion protection gate.
    decay_importance_threshold: float = 0.5

    # Whisper-out (involuntary storage on compaction / session end)
    whisper_out_enabled: bool = True
    whisper_out_min_turns: int = 3
    whisper_out_interval: int = 10  # extract every N user prompts (0 = disabled)

    # Whisper nudge (periodic reminder to use ormah)
    whisper_nudge_interval: int = 10  # Nudge every N prompts (0 = disabled)

    # --- Score contract ------------------------------------------------
    # Two kinds of scores flow through retrieval; every threshold below
    # documents which kind it cuts:
    #   RANK-RELATIVE (ordering only): the blended hybrid `score` — RRF is
    #     min-max normalized per query, so any query's best candidate scores
    #     ~1.0 regardless of absolute quality. Absolute thresholds on it are
    #     meaningless across queries; use it only to order candidates.
    #   ABSOLUTE (gating): `ce_absolute` (cross-encoder score linearly
    #     rescaled from [-12, +6] to [0, 1]) and `raw_cosine` (pre-penalty
    #     vector similarity). Safe to compare against fixed thresholds.

    # Whisper (involuntary recall)
    whisper_max_nodes: int = 6
    # Pre-rerank noise trim: a candidate reaches the reranker if either its
    # RANK-RELATIVE blended score or its ABSOLUTE raw cosine clears this.
    # Its job is only to spare the cross-encoder obvious junk — the absolute
    # injection gate does the real cutting after reranking.
    whisper_min_relevance_score: float = 0.45
    # Candidate pool fed to the reranker/gate = whisper_max_nodes * this
    # multiplier. Retrieve-then-rerank needs a deep pool so the cross-encoder
    # can rescue memories the bi-encoder under-ranked; final injection is
    # still capped at whisper_max_nodes.
    whisper_candidate_pool_multiplier: int = 5
    # Max characters of node content injected for the top full-content
    # whispers; truncated at a word boundary. Full content stays one
    # recall_node call away (the whisper framing says so).
    whisper_injected_content_max_chars: int = 600

    # Whisper reranking (cross-encoder with linear-rescale blended scoring)
    whisper_reranker_enabled: bool = True
    whisper_reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # Post-affinity-boost floor on the RANK-RELATIVE blended score; defines
    # which candidates enter whisper_log and the exploration pool.
    whisper_reranker_min_score: float = 0.40
    whisper_reranker_blend_alpha: float = 0.6
    whisper_reranker_max_doc_chars: int = 512

    # Whisper context buffer (session-aware search enhancement)
    whisper_context_buffer_size: int = 5  # max recent prompts to keep per session
    whisper_session_gap_minutes: int = 10  # prune prompts older than this

    # Whisper intent classification
    whisper_intent_threshold: float = 0.65  # min cosine similarity for intent match

    # Machine-generated turns (subagent task-notifications, scheduled tasks,
    # autonomous-loop checks) reach the UserPromptSubmit hook like any prompt.
    # Whispering into them burns encode+search+rerank where no human reads, and
    # the injection can never be "referenced" — contaminating the usage judge.
    # Defaults cover Claude Code's own markers; add install-specific regexes
    # (headless scripts, other agents) here. Anchored at the prompt start.
    whisper_synthetic_filter_enabled: bool = True
    whisper_synthetic_prompt_patterns: list[str] = []

    # Rot detection for the list above (#143). A pattern that matched before and
    # stopped is stale; a pattern that never matched is merely irrelevant to this
    # install and stays silent.
    whisper_pattern_rot_days: int = 30
    whisper_pattern_monitor_interval_minutes: int = 1440
    # A pattern that fired once, months ago, is not evidence of a live workflow.
    # Proposing its removal is noise, and noise teaches the user to ignore the
    # alert — which defeats the feature. Require a real history before calling
    # anything rotted (council I4).
    whisper_pattern_rot_min_matches: int = 2
    # How much whisper traffic must have happened since a pattern last fired before
    # "it stopped" beats "it just did not come up". Guards against a user returning
    # from vacation and having every pattern proposed as rotted.
    whisper_pattern_rot_min_opportunity: int = 50

    # Whisper topic-shift detection (skip injection when topic unchanged)
    whisper_topic_shift_enabled: bool = True
    whisper_topic_shift_threshold: float = 0.75  # cosine sim above this = same topic

    # Whisper injection gate — cuts the ABSOLUTE gate score (ce_absolute
    # when the reranker ran, raw_cosine otherwise, plus any affinity delta).
    # 0.45 on the ce_absolute scale ≙ raw cross-encoder score −3.9: real
    # paraphrase matches land around raw −3 (≈0.49) while true noise sits
    # below raw −5 (≤0.39); tuned against eval/whisper (gate sweep, 2026-07).
    whisper_injection_gate: float = 0.45

    # Topical-filter vouchers for candidates sharing NO token with the prompt
    # (the fail-closed path): such a candidate survives only with an ABSOLUTE
    # relevance signal. The CE floor matches the injection gate (its added
    # value is keeping no-overlap junk out of the exploration pool); the
    # cosine floor applies when the reranker didn't run.
    whisper_no_overlap_ce_floor: float = 0.45
    whisper_no_overlap_cosine_floor: float = 0.70

    # Standing preferences are applicability rules, not passages that answer
    # the prompt. A separate typed retrieval channel asks the reranker whether
    # each preference applies to the current action, then merges at most two.
    whisper_preference_applicability_enabled: bool = True
    whisper_preference_applicability_gate: float = 0.40
    whisper_preference_max_nodes: int = 2

    # Injection gate when the reranker did not run (unavailable, still
    # downloading, or disabled): the gate then cuts raw_cosine, a weaker
    # absolute signal, so demand a higher bar — degraded mode is more
    # conservative, never noisier. COSINE scale (bge noise floor ~0.5).
    whisper_injection_gate_no_reranker: float = 0.60

    # Deliberate recall floor: results below this are dropped rather than
    # padding to `limit` (recency-vouched temporal supplements exempt).
    # Cuts the RANK-RELATIVE blended score — pragmatic: observed cross-space
    # padding noise scores ~0.30 while relevant results score 0.6+. More
    # permissive than whisper's gate by design; recall is a deliberate act.
    recall_min_relevance_score: float = 0.35

    # Affinity boost (adaptive feedback loop)
    affinity_similarity_threshold: float = 0.70
    affinity_half_life_days: float = 30.0
    affinity_max_boost: float = 0.15
    affinity_implicit_weight: float = 0.8
    whisper_exploration_enabled: bool = True
    feedback_llm_judge_enabled: bool = False
    feedback_llm_judge_min_confidence: float = 0.75

    # Candidate diagnostics are high-volume. Prompt payloads are normalized
    # separately, while stale rejected rows with no feedback references are
    # pruned in bounded background batches. Injected rows are retained for
    # all-time whisper health and exact feedback history.
    whisper_log_rejected_retention_days: int = 30
    whisper_log_cleanup_interval_hours: int = 24
    whisper_log_cleanup_batch_size: int = 1000

    # Space prioritization
    space_boost_global: float = 1.0
    space_boost_other: float = 0.6

    # Ingestion
    ingest_max_content_chars: int = 100000
    ingest_chunk_chars: int = 60000  # >= session_watcher_flush_chars, so a full Batch is ONE call
    # The ingest payload is variable (a Batch is sized to the recall sweet spot), so the provider
    # timeout must be DERIVED from it rather than fixed -- otherwise the batch size is silently
    # capped by whichever provider is configured. Same base+rate idiom as pair_batch.py.
    #
    # Measured 2026-07-26, ONE machine, WHILE AN INGEST DRAIN WAS IN FLIGHT -- so these are upper
    # bounds under contention, not steady state. claude_cli / claude-haiku-4-5, 5 real
    # _extract_memories_llm calls on live 50K-58K-char slices: 37.2 / 32.3 / 45.0 / 74.6 / 61.6 s
    # (median 45.0s, max 74.6s, 0 failures).
    # ollama / gemma3:12b-it-qat, ONE real call (n=1): 75.2s on a 50,577-char slice, 0 failures,
    # 6 memories extracted. Cold-vs-warm model load unestablished for that call.
    #
    # NOT a fitted slope. On the claude_cli sample latency did not track payload size at all
    # (Pearson r = -0.274, n=5; the SLOWEST run had the SMALLEST payload) -- wall clock is
    # dominated by generation volume and provider variance, so no per-10k coefficient can be
    # fitted from this data. 17.5 is a chosen safety envelope, not a measurement.
    #
    # Why 17.5: a full 60000-char Batch renders a ~66,117-char prompt (6.61 units), giving
    # 60 + 17.5 * 6.61 = 175.7s. The ollama observation size-scales to ~87.7s for a full Batch, so
    # 175.7s is ~2.0x that -- ~100% headroom. Scope of that envelope, stated precisely: the
    # claude_cli sample spread 2.31x min->max (32.3->74.6s) and 1.66x median->max. Applied to
    # 87.7s those need 202.6s and 145.4s respectively, so 175.7s COVERS a median->max excursion
    # but NOT a full 2.31x min->max one. It is a large improvement on the 92.4s it replaces, not a
    # guarantee.
    #
    # The trade is deliberately asymmetric: overshooting costs latency in the bad case, while
    # undershooting costs retry churn and eventual quarantine after MAX_EXTRACT_FAILURES. Waiting
    # is the cheaper mistake.
    #
    # ACCEPTED CONSEQUENCE -- unlike the 4.9 this replaces, 17.5 DOES change the live provider:
    # 175.7s exceeds claude_cli's 120s baseline, so claude_cli now waits up to ~176s before
    # declaring failure instead of 120s. Deliberate, not an oversight. Still below
    # ingest_timeout_max_seconds (900), so the cap does not clamp it.
    ingest_timeout_per_10k_chars: float = 17.5
    ingest_timeout_max_seconds: int = 900        # absolute bound for a hung provider
    ingest_min_confidence: float = 0.0  # drop auto-extracted memories below this confidence (0 = off)
    ingest_relevance_gate: bool = True  # drop memories the Extractor labels provenance=material
    ingest_relevance_gate_enforce: bool = False  # False = SHADOW (record would-drops, keep them); True = actually drop

    # Consolidation
    consolidation_interval_minutes: int = 1440
    # Consolidator per-run limits (#89) — defaults preserve the previous
    # hardcoded behavior exactly.
    consolidation_max_clusters_per_run: int = 10
    consolidation_min_cluster_size: int = 2
    consolidation_cluster_threshold: float = 0.6
    consolidation_max_cluster_nodes: int = 5
    # Budget for the WHOLE consolidation prompt, in characters. It governs two things at once:
    # the cluster split (a cluster that does not fit is split, never truncated -- #192) and the
    # Ollama input window the consolidation route pins on its own adapter. They must be the same
    # number: a budget the provider never promised to honor is fiction, and an oversized prompt
    # is then truncated by the Ollama server instead, silently.
    # Sized from measurement (5,923 nodes / 301 real consolidation events): the worst real event
    # builds a 12,961-char prompt and the largest single node is 5,513 chars, so this keeps 1.85x
    # headroom over the worst case observed. At any value >= 16000 none of those 301 events would
    # have been split -- the split is a tail safety net, not the common path.
    consolidation_max_prompt_chars: int = 24000

    # Claude-in-the-loop maintenance
    claude_maintenance_enabled: bool = False
    claude_maintenance_interval_hours: int = 24  # hours between maintenance runs
    claude_maintenance_batch_size: int = 25  # candidates per type per run
    claude_maintenance_cluster_max_chars: int = 24000  # serialized budget per cluster

    # --- Validators ---

    @field_validator("port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"port must be 1–65535, got {v}")
        return v

    @field_validator("ingest_min_confidence")
    @classmethod
    def _ingest_min_confidence_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"ingest_min_confidence must be in [0, 1], got {v}")
        return v

    @field_validator("log_format")
    @classmethod
    def _log_format_enum(cls, v: str) -> str:
        allowed = {"text", "json"}
        if v not in allowed:
            raise ValueError(f"log_format must be one of {allowed}, got {v!r}")
        return v

    @field_validator("log_level")
    @classmethod
    def _log_level_enum(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return upper

    @field_validator("llm_provider")
    @classmethod
    def _llm_provider_enum(cls, v: str) -> str:
        allowed = {"ollama", "litellm", "claude_cli", "none"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of {allowed}, got {v!r}")
        return v

    @field_validator("ingest_llm_provider")
    @classmethod
    def _ingest_llm_provider_enum(cls, v: str) -> str:
        allowed = {"", "ollama", "litellm", "claude_cli", "none"}
        if v not in allowed:
            raise ValueError(f"ingest_llm_provider must be one of {allowed}, got {v!r}")
        return v

    @model_validator(mode="after")
    def _ingest_llm_model_required_when_provider_overridden(self) -> "Settings":
        if self.ingest_llm_provider and self.ingest_llm_provider != "none" and not self.ingest_llm_model:
            raise ValueError(
                "ingest_llm_model is required when ingest_llm_provider is overridden"
            )
        return self

    @field_validator("claude_cli_timeout_seconds")
    @classmethod
    def _claude_cli_timeout_positive(cls, v: int) -> int:
        # A zero/negative timeout would make subprocess.run raise/never wait — the whole
        # extraction budget collapses to an instant failure. Reject it at config load.
        if v < 1:
            raise ValueError(f"claude_cli_timeout_seconds must be >= 1, got {v}")
        return v

    @field_validator("llm_api_key_env_var")
    @classmethod
    def _llm_api_key_env_var_allowed(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        allowed = {
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "COHERE_API_KEY",
            "AZURE_API_KEY",
        }
        if v not in allowed:
            raise ValueError(f"llm_api_key_env_var must be one of {allowed}, got {v!r}")
        return v

    @field_validator("embedding_provider")
    @classmethod
    def _embedding_provider_enum(cls, v: str) -> str:
        allowed = {"local", "ollama", "litellm"}
        if v not in allowed:
            raise ValueError(f"embedding_provider must be one of {allowed}, got {v!r}")
        return v

    @field_validator("llm_timeout_seconds")
    @classmethod
    def _llm_timeout_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"llm_timeout_seconds must be >= 1, got {v}")
        return v

    @field_validator("llm_num_predict")
    @classmethod
    def _llm_num_predict_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"llm_num_predict must be >= 1, got {v}")
        return v

    @field_validator("embedding_dim")
    @classmethod
    def _embedding_dim_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"embedding_dim must be >= 1, got {v}")
        return v

    @field_validator(
        "auto_link_interval_minutes",
        "conflict_check_interval_minutes",
        "duplicate_check_interval_minutes",
        "auto_cluster_interval_minutes",
        "embedding_backfill_interval_minutes",
        "reinforcement_retry_interval_minutes",
    )
    @classmethod
    def _interval_minutes_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"interval must be >= 1 minute, got {v}")
        return v

    @field_validator("embedding_index_max_retries")
    @classmethod
    def _embedding_index_max_retries_nonneg(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"embedding_index_max_retries must be >= 0, got {v}")
        return v

    @field_validator("embedding_index_retry_backoff_seconds")
    @classmethod
    def _embedding_index_backoff_nonneg(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"embedding_index_retry_backoff_seconds must be >= 0, got {v}")
        return v

    @field_validator("hippocampus_debounce_seconds")
    @classmethod
    def _debounce_min(cls, v: float) -> float:
        if v < 0.1:
            raise ValueError(f"hippocampus_debounce_seconds must be >= 0.1, got {v}")
        return v

    @field_validator("session_watcher_debounce_seconds")
    @classmethod
    def _session_watcher_debounce_min(cls, v: float) -> float:
        if v < 10.0:
            raise ValueError(f"session_watcher_debounce_seconds must be >= 10.0, got {v}")
        return v

    @field_validator("session_watcher_reconcile_interval_minutes")
    @classmethod
    def _session_watcher_reconcile_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"session_watcher_reconcile_interval_minutes must be >= 1, got {v}"
            )
        return v

    @field_validator("session_watcher_reconcile_max_per_tick")
    @classmethod
    def _session_watcher_reconcile_cap_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"session_watcher_reconcile_max_per_tick must be >= 1, got {v}"
            )
        return v

    @field_validator("session_watcher_reconcile_max_seconds")
    @classmethod
    def _session_watcher_reconcile_max_seconds_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(
                f"session_watcher_reconcile_max_seconds must be > 0, got {v}"
            )
        return v

    @field_validator("session_watcher_catchup_concurrency")
    @classmethod
    def _catchup_concurrency_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"session_watcher_catchup_concurrency must be >= 1, got {v}")
        return v

    @field_validator("session_watcher_retry_seconds")
    @classmethod
    def _retry_seconds_min(cls, v: float) -> float:
        if v < 1.0:
            raise ValueError(f"session_watcher_retry_seconds must be >= 1.0, got {v}")
        return v

    @field_validator("session_watcher_flush_chars")
    @classmethod
    def _flush_chars_min(cls, v: int) -> int:
        if v < 1000:
            raise ValueError(f"session_watcher_flush_chars must be >= 1000, got {v}")
        return v

    @field_validator("session_watcher_max_raw_bytes")
    @classmethod
    def _max_raw_bytes_min(cls, v: int | None) -> int | None:
        if v is not None and v < 1000:
            raise ValueError(f"session_watcher_max_raw_bytes must be >= 1000, got {v}")
        return v

    @field_validator("ingest_chunk_chars")
    @classmethod
    def _ingest_chunk_chars_bounds(cls, v: int) -> int:
        if v < 1000:
            raise ValueError(f"ingest_chunk_chars must be >= 1000, got {v}")
        return v

    @field_validator("ollama_num_ctx")
    @classmethod
    def _ollama_num_ctx_positive(cls, v: int) -> int:
        # The cross-field capacity check below only runs when the provider resolves to ollama, so
        # without this floor a 0 or negative window is accepted outright under any other provider.
        if v < 1:
            raise ValueError(f"ollama_num_ctx must be >= 1, got {v}")
        return v

    @field_validator("ingest_timeout_per_10k_chars")
    @classmethod
    def _ingest_timeout_rate_non_negative(cls, v: float) -> float:
        # >= 0, NOT > 0 (council R2, Cursor): Task 6 legitimately derives a rate of 0.0 when the
        # provider completes a full batch inside its own baseline. Rejecting 0 would make the
        # measured default unlandable and push the operator into inventing a positive number.
        # 0.0 means "no size term" -- max(baseline, ...) from the hint formula then governs.
        if v < 0:
            raise ValueError(f"ingest_timeout_per_10k_chars must be >= 0, got {v}")
        return v

    @field_validator("ingest_timeout_max_seconds")
    @classmethod
    def _ingest_timeout_max_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"ingest_timeout_max_seconds must be >= 1, got {v}")
        return v

    @model_validator(mode="after")
    def _flush_chars_within_cap(self) -> "Settings":
        if self.session_watcher_flush_chars > self.ingest_chunk_chars:
            raise ValueError(
                f"session_watcher_flush_chars ({self.session_watcher_flush_chars}) must be <= "
                f"ingest_chunk_chars ({self.ingest_chunk_chars}); a chunk smaller than the batch "
                "chops every full Batch into chunk-blind extraction calls, re-introducing the "
                "cross-chunk blindness the sweet-spot sizing exists to remove (ADR-0001 "
                "Amendment 2)"
            )
        if self.ingest_chunk_chars > self.ingest_max_content_chars:
            raise ValueError(
                f"ingest_chunk_chars ({self.ingest_chunk_chars}) must be <= "
                f"ingest_max_content_chars ({self.ingest_max_content_chars})"
            )
        # Vestigial: now transitively implied by the two checks above (flush <= chunk <=
        # max), so this branch can no longer actually fire for any input that passes them.
        # Kept anyway (plan-mandated) for a direct error message if that chain is ever
        # weakened or reordered.
        if self.session_watcher_flush_chars > self.ingest_max_content_chars:
            raise ValueError(
                "session_watcher_flush_chars "
                f"({self.session_watcher_flush_chars}) must be <= "
                f"ingest_max_content_chars ({self.ingest_max_content_chars}); "
                "a larger cap would let a MULTI-turn batch overshoot the extractor's "
                "truncation limit (a single turn bigger than the cap is still truncated, "
                "and logged, regardless of this setting)"
            )
        # Council R1 (Cursor): a bare `>= flush_chars` floor compares BYTES to CHARS and would
        # admit a ~200KB ceiling. Measured raw->clean ratios span 1.1x to 2928x (p50 22.9x, p90
        # 56.5x, p99 223.3x, over 2562 slices, 2026-07-26), so such a ceiling closes tool-heavy
        # slices far below the char sweet spot -- the same axis error Amendment 3 fixes, one scale
        # up, and silently. Anchor the floor on the observed ratio.
        # 25 is kept deliberately: the earlier ~27x p50 it was rounded down from did not reproduce
        # (the measured p50 is 22.9x), so the floor now sits ABOVE the p50 rather than below it --
        # i.e. it is more conservative than its original justification claimed, which is the safe
        # direction for a floor. The value stands; only the rationale needed correcting.
        _MIN_RAW_RATIO = 25
        if (
            self.session_watcher_max_raw_bytes is not None
            and self.session_watcher_max_raw_bytes
            < self.session_watcher_flush_chars * _MIN_RAW_RATIO
        ):
            raise ValueError(
                f"session_watcher_max_raw_bytes ({self.session_watcher_max_raw_bytes}) must be "
                f">= {_MIN_RAW_RATIO}x session_watcher_flush_chars "
                f"({self.session_watcher_flush_chars * _MIN_RAW_RATIO}); the measured raw:clean "
                "ratio is 22.9x at p50 and 56.5x at p90 (this floor uses 25x), so a tighter raw "
                "budget would close batches before the recall sweet spot and become the binding "
                "limit -- reintroducing the axis error ADR-0001 Amendment 3 removes"
            )
        # Council R3 (Codex): the derived ingest hint is min(max(baseline, derived), max), and that
        # min still returns `max` when max < baseline -- e.g. claude_cli (baseline 120) with
        # ingest_timeout_max_seconds=100 emits a 100s hint. Adapters treat the hint as a REPLACEMENT
        # (`timeout_hint_seconds or self.timeout`), so that SHORTENS the provider's own budget on
        # the common short-flush path: the exact regression the floor exists to remove.
        _baseline = (
            self.claude_cli_timeout_seconds
            if (self.ingest_llm_provider or self.llm_provider) == "claude_cli"
            else self.llm_timeout_seconds
        )
        if self.ingest_timeout_max_seconds < _baseline:
            raise ValueError(
                f"ingest_timeout_max_seconds ({self.ingest_timeout_max_seconds}) must be >= the "
                f"active ingest provider's own timeout ({_baseline}); a lower cap makes the hint "
                "SHORTEN the provider's budget, which is the short-flush regression the derived "
                "timeout exists to prevent"
            )
        if (self.ingest_llm_provider or self.llm_provider) == "ollama":
            # A capacity refusal at runtime returns EXTRACT_ERR_CALL_FAILED, which session_watcher
            # maps to TRANSIENT: the cursor is held (correct) but the failure never counts toward
            # MAX_EXTRACT_FAILURES, so a DETERMINISTIC overflow would requeue that transcript
            # forever. Rather than invent a terminal failure state (the quarantine design was
            # descoped 2026-07-25), make the misconfiguration unreachable at boot.
            # Validated against ingest_max_content_chars, NOT flush_chars: an oversized single turn
            # bypasses the batch budget via the parser's progress guard, and _split_for_extraction
            # then emits chunks up to that hard cap.
            from ormah.ingest_capacity import (
                estimated_tokens, prompt_overhead_chars, usable_input_tokens,
            )

            _usable = usable_input_tokens(self)
            _needed = estimated_tokens(self.ingest_max_content_chars + prompt_overhead_chars())
            if _needed > _usable:
                raise ValueError(
                    f"the largest payload ingest can emit (~{_needed} tokens, from "
                    f"ingest_max_content_chars={self.ingest_max_content_chars}) exceeds the usable "
                    f"Ollama input window ({_usable} = ollama_num_ctx {self.ollama_num_ctx} - "
                    f"llm_num_predict {self.llm_num_predict}). Raise ORMAH_OLLAMA_NUM_CTX or lower "
                    "ORMAH_INGEST_MAX_CONTENT_CHARS. Starting anyway would let such a payload fail "
                    "extraction deterministically and retry forever."
                )
        return self

    @model_validator(mode="after")
    def _warn_on_deprecated_flush_bytes(self) -> "Settings":
        # Renamed in ADR-0001 Amendment 3 because the UNIT changed: the old value counted raw
        # transcript bytes, the new one counts conversation chars, and the raw->clean ratio
        # ranges from 1.1x to 2928x (p50 22.9x, p90 56.5x, p99 223.3x, over 2562 slices,
        # 2026-07-26 -- see the measured-ratio note above, near session_watcher_flush_chars).
        # Translating is not possible, so the old value is ignored --
        # but silently ignoring it (what `extra: "ignore"` does today) hides a real config
        # change from the operator. Warn once per process.
        # Council R1 (Codex): checking os.environ ALONE misses the likely case. Settings also reads
        # ~/.config/ormah/.env and ./.env (see _ENV_FILES above), and an operator who set the old
        # key there would get no warning at all -- the exact silent migration this guard exists to
        # prevent. Scan every configured source.
        global _warned_flush_bytes
        if not _warned_flush_bytes:
            key_present = _deprecated_key_present()
            # Latch unconditionally once the scan has run, not only when it found the key:
            # otherwise a clean install (nothing found) never latches, and every subsequent
            # `Settings()` in the process re-scans and can re-emit a warning (review F1).
            _warned_flush_bytes = True
            if key_present:
                logger.warning(
                    "%s is set but no longer used: it was renamed to ORMAH_SESSION_WATCHER_FLUSH_CHARS "
                    "and its unit changed from raw transcript bytes to conversation characters "
                    "(ADR-0001 Amendment 3). The old value was IGNORED; the effective value is %d. "
                    "Remove the old variable, or set the new one deliberately.",
                    _DEPRECATED_FLUSH_BYTES_ENV, self.session_watcher_flush_chars,
                )
        return self

    @field_validator("decay_interval_hours")
    @classmethod
    def _decay_hours_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"decay_interval_hours must be >= 1, got {v}")
        return v

    @field_validator("backup_interval_hours")
    @classmethod
    def _backup_interval_hours_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"backup_interval_hours must be >= 1, got {v}")
        return v

    @field_validator("cloud_backup_interval_hours")
    @classmethod
    def _cloud_backup_interval_hours_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"cloud_backup_interval_hours must be >= 1, got {v}")
        return v

    @field_validator("backup_retention_count")
    @classmethod
    def _backup_retention_count_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"backup_retention_count must be >= 1, got {v}")
        return v

    @field_validator(
        "whisper_log_rejected_retention_days",
        "whisper_log_cleanup_interval_hours",
        "whisper_log_cleanup_batch_size",
    )
    @classmethod
    def _whisper_log_cleanup_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"whisper log cleanup settings must be >= 1, got {v}")
        return v

    @field_validator(
        "whisper_pattern_rot_days",
        "whisper_pattern_monitor_interval_minutes",
        "whisper_pattern_rot_min_matches",
        "whisper_pattern_rot_min_opportunity",
    )
    @classmethod
    def _whisper_pattern_monitor_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"whisper pattern monitor settings must be >= 1, got {v}")
        return v

    @field_validator("core_memory_cap")
    @classmethod
    def _core_cap_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"core_memory_cap must be >= 1, got {v}")
        return v

    @field_validator("fts_weight", "vector_weight")
    @classmethod
    def _search_weight_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"search weight must be >= 0, got {v}")
        return v

    @field_validator("rrf_k")
    @classmethod
    def _rrf_k_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"rrf_k must be >= 1, got {v}")
        return v

    @field_validator("rrf_min_spread_ratio")
    @classmethod
    def _rrf_min_spread_ratio_range(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError(f"rrf_min_spread_ratio must be 0–1, got {v}")
        return v

    @field_validator(
        "similarity_threshold",
        "auto_link_similarity_threshold",
        "auto_merge_threshold",
        "feedback_llm_judge_min_confidence",
        "consolidation_cluster_threshold",
        "whisper_preference_applicability_gate",
    )
    @classmethod
    def _threshold_range(cls, v: float) -> float:
        # `not 0 <= v <= 1` also rejects NaN/inf.
        if not 0 <= v <= 1:
            raise ValueError(f"threshold must be 0–1, got {v}")
        return v

    @field_validator("consolidation_max_clusters_per_run")
    @classmethod
    def _consolidation_max_clusters_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"consolidation_max_clusters_per_run must be >= 0, got {v}")
        return v

    @field_validator("consolidation_min_cluster_size")
    @classmethod
    def _consolidation_min_cluster_size_range(cls, v: int) -> int:
        if v < 2:
            raise ValueError(f"consolidation_min_cluster_size must be >= 2, got {v}")
        return v

    @field_validator("consolidation_max_cluster_nodes")
    @classmethod
    def _consolidation_max_cluster_nodes_range(cls, v: int, info) -> int:
        # Below min_cluster_size, no cluster can ever be emitted; at/above it the
        # runtime guard still applies. Reject the impossible config up front.
        min_size = info.data.get("consolidation_min_cluster_size", 2)
        if v < min_size:
            raise ValueError(
                f"consolidation_max_cluster_nodes ({v}) must be >= "
                f"consolidation_min_cluster_size ({min_size})"
            )
        return v

    @field_validator("forgetting_interval_hours", "deletion_min_archival_days", "deletion_retention_days")
    @classmethod
    def _deletion_days_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"must be >= 1, got {v}")
        return v

    @field_validator("deletion_retrievability_floor", "deletion_strong_edge_weight")
    @classmethod
    def _deletion_unit_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"must be in [0, 1], got {v}")
        return v

    @field_validator("deletion_max_degree", "archival_soft_cap")
    @classmethod
    def _deletion_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"must be >= 0, got {v}")
        return v

    @field_validator("consolidation_max_prompt_chars")
    @classmethod
    def _consolidation_max_prompt_chars_floor(cls, v: int) -> int:
        # The prompt template alone costs ~2,440 chars. Below 4000 there is no room left for two
        # sources of any useful size, so no cluster could ever be consolidated -- reject the
        # impossible config up front rather than emitting a silent no-op every run.
        if v < 4000:
            raise ValueError(f"consolidation_max_prompt_chars must be >= 4000, got {v}")
        return v

    @field_validator("activation_decay")
    @classmethod
    def _activation_decay_range(cls, v: float) -> float:
        if not 0 < v <= 1:
            raise ValueError(f"activation_decay must be (0, 1], got {v}")
        return v

    @field_validator(
        "importance_access_weight",
        "importance_edge_weight",
        "importance_recency_weight",
    )
    @classmethod
    def _importance_weight_range(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError(f"importance weight must be 0–1, got {v}")
        return v

    @field_validator(
        "importance_access_reference",
        "importance_edge_reference",
    )
    @classmethod
    def _importance_reference_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"importance reference must be >= 1, got {v}")
        return v

    @field_validator("decay_importance_threshold", "fsrs_decay_threshold")
    @classmethod
    def _decay_threshold_range(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError(f"threshold must be 0–1, got {v}")
        return v

    @field_validator(
        "fsrs_initial_stability",
        "fsrs_max_stability",
        "fsrs_growth_factor",
        "fsrs_growth_exponent",
        "fsrs_spacing_cap",
        "fsrs_reinforcement_cooldown_days",
    )
    @classmethod
    def _fsrs_finite(cls, v: float) -> float:
        # The bounds checks below cannot do this: every `v <= 0` / `v < 1` /
        # `v < 0` comparison is False for NaN, so NaN passes all of them, and
        # infinity satisfies them outright. A NaN growth factor propagates NaN
        # into stability, which is then serialized into the Markdown frontmatter;
        # a NaN cooldown raises inside timedelta.
        if not math.isfinite(v):
            raise ValueError(f"FSRS parameter must be finite, got {v}")
        return v

    @field_validator(
        "fsrs_initial_stability",
        "fsrs_growth_factor",
        "fsrs_growth_exponent",
    )
    @classmethod
    def _fsrs_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"FSRS parameter must be > 0, got {v}")
        return v

    @field_validator("fsrs_spacing_cap")
    @classmethod
    def _fsrs_spacing_cap_min(cls, v: float) -> float:
        # Below 1 the spacing factor would shrink stability on use.
        if v < 1:
            raise ValueError(f"fsrs_spacing_cap must be >= 1, got {v}")
        return v

    @field_validator("fsrs_reinforcement_cooldown_days")
    @classmethod
    def _fsrs_cooldown_non_negative(cls, v: float) -> float:
        # 0 is valid: it disables the cooldown.
        if v < 0:
            raise ValueError(f"fsrs_reinforcement_cooldown_days must be >= 0, got {v}")
        return v

    @field_validator("importance_recency_half_life_days")
    @classmethod
    def _importance_half_life_positive(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"importance_recency_half_life_days must be finite, got {v}")
        if v <= 0:
            raise ValueError(f"importance_recency_half_life_days must be > 0, got {v}")
        return v

    @field_validator("fsrs_max_stability")
    @classmethod
    def _fsrs_max_stability_positive(cls, v: float) -> float:
        if v < 1:
            raise ValueError(f"fsrs_max_stability must be >= 1, got {v}")
        return v

    @field_validator("ingest_max_content_chars")
    @classmethod
    def _ingest_max_content_chars_min(cls, v: int) -> int:
        if v < 1000:
            raise ValueError(f"ingest_max_content_chars must be >= 1000, got {v}")
        return v

    @field_validator("importance_recompute_interval_minutes", "consolidation_interval_minutes")
    @classmethod
    def _enrichment_interval_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"interval must be >= 1 minute, got {v}")
        return v

    @field_validator("claude_maintenance_cluster_max_chars")
    @classmethod
    def _claude_maintenance_cluster_max_chars_min(cls, v: int) -> int:
        if v < 1000:
            raise ValueError(f"claude_maintenance_cluster_max_chars must be >= 1000, got {v}")
        return v

    @property
    def llm_enabled(self) -> bool:
        """True when an LLM provider is configured (not ``"none"``).

        This is a FIVE-subsystem master switch, not a per-job flag, and it deliberately ignores
        ``ingest_llm_provider``. Flipping the provider to ``"none"`` takes down ``auto_linker``,
        ``conflict_detector``, ``duplicate_merger``, ``consolidator`` and the ``session_watcher``
        feedback judge together.

        It also fails SILENTLY GREEN: those jobs return ``{"skipped": "llm_disabled"}``, which
        ``job_tracker.failure_reason`` does not classify as a failure, so the sleep cycle records
        a success and reports ``status: "completed"`` for work that never ran. Decay and forgetting
        are NOT gated here and keep pruning, and ``MemoryEngine._auto_link_node`` keeps writing
        untyped ``related_to`` edges with no LLM at all -- so the graph keeps shrinking and stops
        being curated, with nothing in the health output to show for it.

        Anyone wanting to quiet ONE job needs code: the per-job settings are intervals only and
        the validator rejects anything below 1 minute.
        """
        return self.llm_provider != "none"

    @property
    def nodes_dir(self) -> Path:
        return self.memory_dir / "nodes"

    @property
    def db_path(self) -> Path:
        return self.memory_dir / "index.db"


def validate_llm_runtime_config(settings: "Settings") -> None:
    """Server-startup guard — deliberately NOT a pydantic validator (council C2): the
    eager global `settings` singleton is imported by `ormah setup`, and a model
    validator would crash the exact repair path a user with this legacy pair needs
    (the installer runs `ormah setup --update` under `set -e`). The server process is
    where the misconfiguration does silent damage (404 per maintenance call), so the
    server is where it fails loudly. Rejects BOTH failure shapes (council C3): an
    Anthropic model id (the field default leaking through) and an empty/whitespace
    model (ORMAH_LLM_MODEL= overrides the default with "", which Ollama also 404s).
    """
    if settings.llm_provider == "ollama":
        model = (settings.llm_model or "").strip()
        if not model or model.startswith("claude-"):
            raise ValueError(
                "llm_model is empty or looks like an Anthropic model id but "
                "llm_provider=ollama; set ORMAH_LLM_MODEL to an installed Ollama "
                "model (e.g. gemma3:12b-it-qat)"
            )


settings = Settings()
