"""Issue #87: pair batching — settings, timeout hint, batch module."""
from ormah.config import Settings


def test_batching_settings_defaults(tmp_path):
    s = Settings(memory_dir=tmp_path)
    assert s.maintenance_pairs_per_call == 1          # K=1 -> legacy flow untouched
    assert s.maintenance_timeout_per_pair_seconds == 10
    # per-job K overrides (council C3): 0 = fall back to the global K
    assert s.auto_link_pairs_per_call == 0
    assert s.duplicate_check_pairs_per_call == 0
    assert s.conflict_check_pairs_per_call == 0
    # caps default to CURRENT-equivalent bounds (council I1): 0 = unbounded
    assert s.auto_link_max_pairs_per_run == 0
    assert s.duplicate_check_max_pairs_per_run == 0
    assert s.conflict_check_max_pairs_per_run == 10000   # today's exact bound
