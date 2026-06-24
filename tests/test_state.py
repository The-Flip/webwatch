"""Tests for run-to-run state: anti-flap thresholds and transition detection."""

from __future__ import annotations

from webwatch.result import CheckResult
from webwatch.state import apply_results, load_state, mark_notified, save_state


def _mismatch() -> CheckResult:
    return CheckResult.mismatch("s", "hours", expected="9-5", observed="10-6")


def _fetch_error() -> CheckResult:
    return CheckResult.fetch_error("s", "hours", detail="timeout")


def _structure_changed() -> CheckResult:
    return CheckResult.structure_changed("s", "hours", detail="gone")


def _ok() -> CheckResult:
    return CheckResult.ok("s", "hours", expected="9-5", observed="9-5")


def test_first_failure_below_threshold_does_not_alert() -> None:
    state, transitions = apply_results({}, [_mismatch()], alert_after=2, recover_after=1)
    assert transitions == []
    assert state["s\thours"].unhealthy_streak == 1


def test_alerts_after_consecutive_failures() -> None:
    state, _ = apply_results({}, [_mismatch()], alert_after=2, recover_after=1)
    state, transitions = apply_results(state, [_mismatch()], alert_after=2, recover_after=1)
    assert [t.kind for t in transitions] == ["alert"]
    assert state["s\thours"].alerting


def test_streak_survives_changing_failure_type() -> None:
    """Error-type drift must not reset the counter (agy Gap E)."""
    state, t1 = apply_results({}, [_fetch_error()], alert_after=2, recover_after=1)
    state, t2 = apply_results(state, [_structure_changed()], alert_after=2, recover_after=1)
    assert t1 == []
    assert [t.kind for t in t2] == ["alert"]  # escalated despite different statuses


def test_recovery_after_healthy_run() -> None:
    state, _ = apply_results({}, [_mismatch()], alert_after=1, recover_after=1)
    assert state["s\thours"].alerting
    state, transitions = apply_results(state, [_ok()], alert_after=1, recover_after=1)
    assert [t.kind for t in transitions] == ["recover"]
    assert not state["s\thours"].alerting


def test_healthy_runs_never_alert() -> None:
    _state, transitions = apply_results({}, [_ok()], alert_after=1, recover_after=1)
    assert transitions == []


def test_save_and_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "state.json"
    state, _ = apply_results({}, [_mismatch()], alert_after=2, recover_after=1)
    save_state(state, path)
    loaded = load_state(path)
    assert loaded["s\thours"].unhealthy_streak == 1
    assert loaded["s\thours"].status == "mismatch"


def test_load_missing_file_is_empty(tmp_path) -> None:
    assert load_state(tmp_path / "nope.json") == {}


def test_alert_does_not_refire_once_notified() -> None:
    state, first = apply_results({}, [_mismatch()], alert_after=1, recover_after=1)
    assert [t.kind for t in first] == ["alert"]
    mark_notified(state, first)  # the send succeeded
    state, second = apply_results(state, [_mismatch()], alert_after=1, recover_after=1)
    assert second == []  # already notified -> quiet


def test_alert_refires_until_notified() -> None:
    """If the send failed (notified not set), the alert retries next run (no dropped alarm)."""
    state, first = apply_results({}, [_mismatch()], alert_after=1, recover_after=1)
    assert [t.kind for t in first] == ["alert"]
    # do NOT mark_notified -> simulate a failed send
    state, second = apply_results(state, [_mismatch()], alert_after=1, recover_after=1)
    assert [t.kind for t in second] == ["alert"]
