"""Issue #90: maintenance runs return a stats dict."""
from ormah.background.auto_linker import run_auto_linker
from ormah.background.conflict_detector import run_conflict_detection
from ormah.background.duplicate_merger import run_duplicate_detection


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


def test_llm_jobs_are_staggered(engine, monkeypatch):
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
