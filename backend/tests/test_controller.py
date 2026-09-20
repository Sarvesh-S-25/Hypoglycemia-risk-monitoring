"""
Controller unit tests -- the priority test suite per AGENTS.md ("it holds the
clinical logic"). Covers docs/PLAN.md section 3's Phase 2 "done when" criteria:

    unit tests drive synthetic risk/battery sequences and assert the mode
    path, that no alert fires without a completed confirmation window, and
    that the scheduler picks the right next time in all four branches.
"""
from __future__ import annotations

from app.config import settings
from app.controller import Controller, schedule_next_foot_check, should_fire_foot_check


def feed(c: Controller, scores, battery_pct=80, sqi=1, start_ts=0.0, step=1.0):
    """Helper: feed a sequence of scores through evaluate(), return the list
    of ControllerDecision objects in order."""
    decisions = []
    for i, score in enumerate(scores):
        decisions.append(c.evaluate(score=score, battery_pct=battery_pct, sqi=sqi, timestamp=start_ts + i * step))
    return decisions


# --- Mode selection ----------------------------------------------------------


def test_default_mode_is_normal_for_mid_range_score():
    c = Controller()
    d = c.evaluate(score=0.4, battery_pct=80, sqi=1)
    assert d.mode == "Normal"


def test_low_score_alone_does_not_trigger_eco_without_low_battery():
    """Eco requires risk low AND battery low AND SQI stable -- a low score
    with healthy battery must stay Normal."""
    c = Controller()
    decisions = feed(c, [0.1] * (settings.sqi_stable_window + 1), battery_pct=90)
    assert decisions[-1].mode == "Normal"


def test_eco_requires_all_three_conditions():
    c = Controller()
    decisions = feed(
        c,
        [settings.risk_low - 0.05] * (settings.sqi_stable_window + 1),
        battery_pct=settings.battery_eco_pct - 1,
        sqi=1,
    )
    assert decisions[-1].mode == "Eco"


def test_eco_blocked_by_unstable_sqi():
    c = Controller()
    scores = [settings.risk_low - 0.05] * (settings.sqi_stable_window + 1)
    decisions = []
    for i, score in enumerate(scores):
        # inject one rejected window partway through -- breaks "SQI stable"
        sqi = 0 if i == 2 else 1
        decisions.append(c.evaluate(score=score, battery_pct=10, sqi=sqi, timestamp=float(i)))
    assert decisions[-1].mode != "Eco"


def test_watch_on_elevated_score():
    c = Controller()
    d = c.evaluate(score=(settings.risk_elevated + settings.risk_alert) / 2, battery_pct=80, sqi=1)
    assert d.mode == "Watch"


def test_watch_on_rising_trend_even_below_elevated_threshold():
    c = Controller()
    # Monotonically increasing scores, all below risk_elevated, but a
    # meaningful rise over the trend window should still trigger Watch.
    low = settings.risk_low
    rising = [low, low + 0.03, low + 0.10]
    decisions = feed(c, rising, battery_pct=80)
    assert decisions[-1].mode == "Watch"


def test_verify_on_score_above_alert_threshold():
    c = Controller()
    d = c.evaluate(score=settings.risk_alert + 0.05, battery_pct=80, sqi=1)
    assert d.mode == "Verify"


# --- Sustained-risk confirmation: the most important guarantee ---------------


def test_single_spike_does_not_fire_alert():
    """A single window above risk_alert must NOT fire an alert -- this is the
    entire justification for the false-alert-rate result (SRD section 6)."""
    c = Controller()
    d = c.evaluate(score=settings.risk_alert + 0.1, battery_pct=80, sqi=1)
    assert d.mode == "Verify"
    assert d.fire_alert is False


def test_alert_fires_only_after_confirm_windows_consecutive_high_scores():
    c = Controller()
    high = settings.risk_alert + 0.1
    decisions = feed(c, [high] * settings.confirm_windows, battery_pct=80)
    # No alert before the last confirmation window
    assert all(not d.fire_alert for d in decisions[:-1])
    assert decisions[-1].fire_alert is True
    # After firing, mode drops back to Watch per SRD 4.4
    assert decisions[-1].mode == "Watch"


def test_confirmation_resets_if_score_drops_below_alert_mid_sequence():
    c = Controller()
    high = settings.risk_alert + 0.1
    low = settings.risk_alert - 0.2
    # High, high, then a drop -- confirmation must reset, not carry over.
    seq = [high] * (settings.confirm_windows - 1) + [low] + [high] * settings.confirm_windows
    decisions = feed(c, seq, battery_pct=80)
    # The only fire_alert=True must be the LAST window (a fresh confirmation
    # run starting after the dip), not an early one that ignored the reset.
    fire_indices = [i for i, d in enumerate(decisions) if d.fire_alert]
    assert fire_indices == [len(decisions) - 1]


def test_alert_cooldown_prevents_immediate_refire():
    c = Controller()
    high = settings.risk_alert + 0.1
    # Fire once, then keep feeding high scores well within the cooldown window.
    seq = [high] * settings.confirm_windows + [high] * settings.confirm_windows
    decisions = feed(c, seq, battery_pct=80, step=1.0)
    fire_count = sum(1 for d in decisions if d.fire_alert)
    assert fire_count == 1, f"expected exactly one alert within cooldown, got {fire_count}"


def test_alert_can_refire_after_cooldown_elapses():
    c = Controller()
    high = settings.risk_alert + 0.1
    first_batch = feed(c, [high] * settings.confirm_windows, battery_pct=80, start_ts=0.0, step=1.0)
    assert first_batch[-1].fire_alert is True

    # Score drops, mode leaves Verify, confirmation resets naturally.
    c.evaluate(score=0.1, battery_pct=80, sqi=1, timestamp=1000.0)

    # Well past alert_cooldown_s later, a fresh sustained-risk episode.
    later_start = 1000.0 + settings.alert_cooldown_s + 10
    second_batch = feed(c, [high] * settings.confirm_windows, battery_pct=80, start_ts=later_start, step=1.0)
    assert second_batch[-1].fire_alert is True


# --- Manual override ----------------------------------------------------------


def test_manual_override_forces_mode_and_suppresses_automatic_selection():
    c = Controller()
    c.set_manual_mode("Watch")
    d = c.evaluate(score=0.05, battery_pct=95, sqi=1)  # would otherwise be Eco or Normal
    assert d.mode == "Watch"


def test_manual_override_cleared_resumes_automatic_selection():
    c = Controller()
    c.set_manual_mode("Watch")
    c.evaluate(score=0.05, battery_pct=95, sqi=1)
    c.set_manual_mode(None)
    d = c.evaluate(score=0.05, battery_pct=95, sqi=1)
    assert d.mode != "Watch" or d.mode == "Normal"  # falls back to automatic selection


def test_manual_override_reset_clears_verify_confirmation_progress():
    c = Controller()
    high = settings.risk_alert + 0.1
    # Get partway through a confirmation run.
    feed(c, [high] * (settings.confirm_windows - 1), battery_pct=80)
    c.set_manual_mode("Eco")  # operator forces a different mode mid-confirmation
    c.set_manual_mode(None)  # then returns control
    # A single subsequent high score should NOT immediately fire, since the
    # override must have reset the confirmation counter.
    d = c.evaluate(score=high, battery_pct=80, sqi=1)
    assert d.fire_alert is False


# --- Foot-check scheduler: all four branches (SRD 4.4) -----------------------


def test_schedule_normal_result_gives_24h():
    d = schedule_next_foot_check(last_result_valid=True, last_delta_t=0.8, now=1000.0)
    assert d.action == "scheduled_24h"
    assert d.next_check_scheduled == 1000.0 + settings.foot_check_normal_interval_s


def test_schedule_elevated_result_gives_8h():
    elevated = settings.foot_check_elevated_threshold_c + 0.1
    d = schedule_next_foot_check(last_result_valid=True, last_delta_t=elevated, now=1000.0)
    assert d.action == "scheduled_8h"
    assert d.next_check_scheduled == 1000.0 + settings.foot_check_elevated_interval_s


def test_schedule_boundary_delta_t_is_not_elevated():
    """SRD 4.4 says 'elevated' is >2.2C, so exactly at the threshold is normal."""
    d = schedule_next_foot_check(
        last_result_valid=True, last_delta_t=settings.foot_check_elevated_threshold_c, now=1000.0
    )
    assert d.action == "scheduled_24h"


def test_schedule_invalid_result_gives_1h_retry_regardless_of_delta_t():
    d = schedule_next_foot_check(last_result_valid=False, last_delta_t=5.0, now=1000.0)
    assert d.action == "retry_1h"
    assert d.next_check_scheduled == 1000.0 + settings.foot_check_invalid_retry_s


def test_should_fire_when_scheduled_time_reached_and_battery_sufficient():
    assert should_fire_foot_check(scheduled_time=1000.0, battery_pct=50, now=1000.0) is True
    assert should_fire_foot_check(scheduled_time=1000.0, battery_pct=50, now=1500.0) is True


def test_should_not_fire_before_scheduled_time():
    assert should_fire_foot_check(scheduled_time=2000.0, battery_pct=50, now=1000.0) is False


def test_should_not_fire_when_battery_insufficient():
    assert should_fire_foot_check(
        scheduled_time=1000.0, battery_pct=settings.battery_aux_min - 1, now=1000.0
    ) is False


def test_should_not_fire_with_no_schedule():
    assert should_fire_foot_check(scheduled_time=None, battery_pct=100, now=1000.0) is False
