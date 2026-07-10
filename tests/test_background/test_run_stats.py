"""Issue #90: maintenance runs return a stats dict."""
import pytest

from ormah.background import auto_linker
from ormah.background import duplicate_merger
from ormah.background.auto_linker import run_auto_linker
from ormah.background.conflict_detector import run_conflict_detection
from ormah.background.duplicate_merger import run_duplicate_detection
from ormah.background.job_tracker import JobTracker, tracked


def test_auto_linker_returns_stats(engine):
    engine.settings.llm_provider = "none"  # llm disabled -> early return, still a dict
    stats = run_auto_linker(engine)
    assert stats == {"skipped": "llm_disabled"}


def test_conflict_detector_stats_shape(engine):
    # enable llm; no candidates exist, so no LLM call happens
    engine.settings.llm_provider = "ollama"
    stats = run_conflict_detection(engine)
    for key in ("candidates_found", "pairs_evaluated", "edges_created", "duration_s"):
        assert key in stats


def test_duplicate_merger_stats_shape(engine):
    engine.settings.llm_provider = "ollama"
    stats = run_duplicate_detection(engine)
    for key in ("nodes_scanned", "pairs_evaluated", "proposals_created", "duration_s"):
        assert key in stats


def test_run_failure_is_visible_as_error_stats(engine, monkeypatch):
    """A run whose internals raise must NOT look like a clean, empty success."""
    engine.settings.llm_provider = "ollama"

    def boom(conn):
        raise RuntimeError("watermark read failed")

    monkeypatch.setattr(auto_linker, "_get_watermark", boom)

    stats = run_auto_linker(engine)
    assert stats is not None
    assert stats["error"] == "watermark read failed"

    # tracked() must route the error dict to record_failure, not record_success
    # (council R2 finding 4: last_stats alone doesn't prove the routing).
    tracker = JobTracker()
    job = tracked(tracker, "auto_linker", run_auto_linker, engine)
    job()
    snap = tracker.snapshot()["auto_linker"]
    assert snap["error_count"] == 1
    assert snap["last_error"] == "watermark read failed"
    assert snap["last_success"] is None
    assert snap["last_stats"] is not None
    assert "error" in snap["last_stats"]


def test_find_link_candidates_propagates_finder_failure(engine, monkeypatch):
    """Issue #90 council R2 finding 1: a DB/encoder failure inside the finder
    must not be swallowed as "no candidates". _find_link_candidates is only
    called by get_maintenance_batches (run_auto_linker has its own inline
    candidate loop and never calls this finder), so there is no run_*/tracked()
    path to exercise here — the finder itself must raise."""

    def boom(*a, **kw):
        raise RuntimeError("encoder boom")

    # get_encoder is imported locally inside the function; patch the source module.
    import ormah.embeddings.encoder as encoder_mod
    monkeypatch.setattr(encoder_mod, "get_encoder", boom)

    with pytest.raises(RuntimeError, match="encoder boom"):
        auto_linker._find_link_candidates(engine)


def test_find_merge_candidates_propagates_finder_failure(engine, monkeypatch):
    """Same as above for duplicate_merger's finder (also only reachable via
    get_maintenance_batches, never via the scheduled run_duplicate_detection)."""

    def boom(*a, **kw):
        raise RuntimeError("encoder boom")

    import ormah.embeddings.encoder as encoder_mod
    monkeypatch.setattr(encoder_mod, "get_encoder", boom)

    with pytest.raises(RuntimeError, match="encoder boom"):
        duplicate_merger._find_merge_candidates(engine)


def test_conflict_detector_finder_failure_is_visible_via_tracked(engine, monkeypatch):
    """Issue #90 council R2 finding 1: unlike auto_linker/duplicate_merger,
    run_conflict_detection DOES call _find_conflict_candidates directly, so an
    internal finder failure (not the finder-doesn't-exist case) must surface
    through tracked() as a recorded failure, not a green run. Patches the
    encoder (called unconditionally near the top of the finder) rather than
    the finder function itself, so this actually exercises the finder's own
    (now-removed) blanket except."""
    import ormah.embeddings.encoder as encoder_mod

    def boom(*a, **kw):
        raise RuntimeError("encoder boom")

    monkeypatch.setattr(encoder_mod, "get_encoder", boom)
    engine.settings.llm_provider = "ollama"

    tracker = JobTracker()
    job = tracked(tracker, "conflict_detector", run_conflict_detection, engine)
    job()
    snap = tracker.snapshot()["conflict_detector"]
    assert snap["error_count"] == 1
    assert snap["last_success"] is None
    assert snap["last_error"] is not None


def test_consolidator_finder_failure_is_visible_via_tracked(engine, monkeypatch):
    """run_consolidation calls _find_consolidation_clusters directly and has no
    catch-all of its own — an internal VectorStore-construction failure must
    reach tracked()'s own except, not the finder's (now-removed) blanket except."""
    from ormah.background.consolidator import run_consolidation
    from ormah.models.node import CreateNodeRequest, NodeType

    # Need >= 2 working-tier nodes to get past the "nothing to cluster" early
    # return and actually reach the VectorStore(...) construction.
    for i in range(2):
        engine.remember(CreateNodeRequest(content=f"note number {i}", type=NodeType.fact, title=f"n{i}"))

    import ormah.embeddings.vector_store as vs_mod

    class _BoomVectorStore:
        def __init__(self, *a, **kw):
            raise RuntimeError("vector store boom")

    monkeypatch.setattr(vs_mod, "VectorStore", _BoomVectorStore)
    engine.settings.llm_provider = "ollama"

    tracker = JobTracker()
    job = tracked(tracker, "consolidator", run_consolidation, engine)
    job()
    snap = tracker.snapshot()["consolidator"]
    assert snap["error_count"] == 1
    assert snap["last_success"] is None
    assert snap["last_error"] is not None


def test_llm_jobs_are_staggered(engine, monkeypatch):
    """At default (1440-minute) intervals, all four offsets fit under the
    interval and stay distinct."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from ormah.background import scheduler as sched_mod

    recorded = {}
    orig_add = BackgroundScheduler.add_job

    def spy(self, func, *a, **kw):
        recorded[kw.get("id")] = kw.get("next_run_time")
        return orig_add(self, func, *a, **kw)

    monkeypatch.setattr(BackgroundScheduler, "add_job", spy)
    monkeypatch.setattr(BackgroundScheduler, "start", lambda self: None)
    sched_mod.start_scheduler(engine)
    llm_jobs = ["auto_linker", "conflict_detector", "duplicate_merger", "consolidator"]
    times = [recorded[j] for j in llm_jobs]
    assert all(t is not None for t in times)
    assert len({t.replace(microsecond=0) for t in times}) == len(times)


def test_staggered_offsets_scale_and_stay_distinct(engine, monkeypatch):
    """Issue #90 council R2 finding 3: clamping offsets with min() collapses
    distinct offsets onto the same boundary at short intervals (e.g. interval=30
    -> [5,15,30,30], interval=1 -> [1,1,1,1]), recreating the concurrent-LLM-load
    burst the stagger exists to prevent. Offsets must instead scale
    proportionally so they stay distinct and always land inside one interval."""
    from datetime import timedelta, timezone
    from apscheduler.schedulers.background import BackgroundScheduler
    from ormah.background import scheduler as sched_mod

    llm_jobs = ["auto_linker", "conflict_detector", "duplicate_merger", "consolidator"]

    def run_with_interval(interval_minutes: int) -> dict:
        engine.settings.auto_link_interval_minutes = interval_minutes
        engine.settings.conflict_check_interval_minutes = interval_minutes
        engine.settings.duplicate_check_interval_minutes = interval_minutes
        engine.settings.consolidation_interval_minutes = interval_minutes

        recorded = {}
        orig_add = BackgroundScheduler.add_job

        def spy(self, func, *a, **kw):
            recorded[kw.get("id")] = kw.get("next_run_time")
            return orig_add(self, func, *a, **kw)

        monkeypatch.setattr(BackgroundScheduler, "add_job", spy)
        monkeypatch.setattr(BackgroundScheduler, "start", lambda self: None)

        from datetime import datetime
        before = datetime.now(timezone.utc)
        sched_mod.start_scheduler(engine)

        for job_id in llm_jobs:
            t = recorded[job_id]
            assert t is not None
            assert t < before + timedelta(minutes=interval_minutes)
        return recorded

    for interval_minutes in (1, 30):
        recorded = run_with_interval(interval_minutes)
        times = [recorded[j] for j in llm_jobs]
        assert len({t.replace(microsecond=0) for t in times}) == len(times), (
            f"offsets collapsed at interval_minutes={interval_minutes}: {times}"
        )
