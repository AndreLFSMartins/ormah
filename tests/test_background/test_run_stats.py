"""Issue #90: maintenance runs return a stats dict."""
from ormah.background import auto_linker
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

    # tracked() must store the error dict as last_stats, not None.
    tracker = JobTracker()
    job = tracked(tracker, "auto_linker", run_auto_linker, engine)
    job()
    last_stats = tracker.snapshot()["auto_linker"]["last_stats"]
    assert last_stats is not None
    assert "error" in last_stats


def test_llm_jobs_are_staggered(engine, monkeypatch):
    """At default (1440-minute) intervals, all four offsets fit under the
    interval and stay distinct. See test_staggered_offset_bounded_by_configured_interval
    for the short-interval case where the offsets collapse (issue #90 finding 3)."""
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


def test_staggered_offset_bounded_by_configured_interval(engine, monkeypatch):
    """Issue #90 (council finding 3): a fixed stagger offset must never exceed
    a job's own configured interval — otherwise a supported short interval
    (e.g. consolidation_interval_minutes=1) waits up to 45 minutes for its
    first run after every restart, instead of the ~1 minute the base gave it."""
    from datetime import timedelta, timezone
    from apscheduler.schedulers.background import BackgroundScheduler
    from ormah.background import scheduler as sched_mod

    engine.settings.auto_link_interval_minutes = 1
    engine.settings.conflict_check_interval_minutes = 1
    engine.settings.duplicate_check_interval_minutes = 1
    engine.settings.consolidation_interval_minutes = 1

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

    llm_jobs = ["auto_linker", "conflict_detector", "duplicate_merger", "consolidator"]
    for job_id in llm_jobs:
        t = recorded[job_id]
        assert t is not None
        assert t <= before + timedelta(minutes=1, seconds=5)
