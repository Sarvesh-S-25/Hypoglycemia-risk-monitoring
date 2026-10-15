"""
controller.py -- the discrete-mode state machine, sustained-risk confirmation,
and the deterministic foot-check scheduler (SRD 4.4, docs/PLAN.md section 4).

This is the one file in the repository that carries clinical-adjacent logic.
Per AGENTS.md, the frontend never re-derives any of this -- it only displays
what this module decides. Two independent implementations of "when does an
alert fire" is the single most likely way this system embarrasses itself in a
demo (docs/PLAN.md section 1, decision 2), so this module is also the most
heavily unit-tested part of the backend (tests/test_controller.py).

Mode transition table (SRD 4.4, thresholds in app/config.py):

    any -> Verify   if score >= risk_alert
    any -> Watch    if risk_elevated <= score < risk_alert, or risk trending up
    any -> Eco      if score < risk_low AND battery low AND SQI stable
    any -> Normal   otherwise

Verify is sticky: once entered, it holds until either `confirm_windows`
consecutive windows above risk_alert have been seen (fire the alert, then drop
to Watch and start the cooldown) or the score falls below risk_alert (drop to
Watch without firing). A single spike must never fire an alert on its own --
that is the entire justification for the false-alert-rate result in SRD
section 6.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings

logger = logging.getLogger("glucosentry.controller")

Mode = str  # "Eco" | "Normal" | "Watch" | "Verify" -- see app.models.Mode


@dataclass
class ControllerState:
    mode: Mode = "Normal"
    manual_mode: Optional[Mode] = None  # set by POST /api/controller/mode; overrides automatic selection
    verify_confirm_count: int = 0
    # None means "no alert has ever fired in this session" -- deliberately not
    # 0.0, because 0.0 is indistinguishable from a real (if unlikely) epoch
    # timestamp and would make the very first alert of a session that starts
    # near t=0 (e.g. relative timestamps in a test) look like it's within the
    # cooldown of a phantom prior alert. Found via test_controller.py's
    # cooldown tests failing when they used small relative timestamps.
    last_alert_ts: Optional[float] = None
    recent_scores: deque = field(default_factory=lambda: deque(maxlen=max(
        settings.watch_trend_window, settings.confirm_windows
    )))
    recent_sqi: deque = field(default_factory=lambda: deque(maxlen=settings.sqi_stable_window))


@dataclass
class ControllerDecision:
    mode: Mode
    fire_alert: bool
    score: float
    timestamp: float


class Controller:
    """Call `evaluate()` once per scored window. Stateful across calls --
    one Controller instance per session, owned by app/main.py's lifespan."""

    def __init__(self) -> None:
        self.state = ControllerState()
        self._last_battery_pct: Optional[int] = None

    def set_manual_mode(self, mode: Optional[Mode]) -> None:
        """POST /api/controller/mode. mode=None returns control to automatic
        selection (docs/API_CONTRACT.md section 3)."""
        self.state.manual_mode = mode
        if mode is not None:
            self.state.mode = mode
            # Manual override resets Verify's confirmation progress -- an
            # operator forcing a mode change mid-confirmation should not have
            # a stale count silently resume and fire later.
            self.state.verify_confirm_count = 0
            logger.info("controller: manual override -> %s", mode)
        else:
            logger.info("controller: manual override cleared, resuming automatic mode selection")

    def evaluate(
        self, score: float, battery_pct: Optional[int], sqi: int, timestamp: Optional[float] = None
    ) -> ControllerDecision:
        ts = timestamp if timestamp is not None else time.time()
        s = self.state
        s.recent_scores.append(score)
        s.recent_sqi.append(sqi)
        self._last_battery_pct = battery_pct

        if s.manual_mode is not None:
            # Manual override still runs Verify's confirmation counter so an
            # operator watching a forced Verify mode sees consistent alert
            # behavior, but automatic mode transitions are suppressed.
            new_mode = s.manual_mode
        else:
            new_mode = self._select_mode(score)

        fire_alert = False
        if new_mode == "Verify":
            if score >= settings.risk_alert:
                s.verify_confirm_count += 1
            else:
                # Score dropped back below the alert threshold while in
                # Verify -- per SRD 4.4, drop to Watch without firing.
                s.verify_confirm_count = 0
                if s.manual_mode is None:
                    new_mode = "Watch"

            if s.verify_confirm_count >= settings.confirm_windows:
                cooldown_elapsed = (
                    s.last_alert_ts is None or (ts - s.last_alert_ts) >= settings.alert_cooldown_s
                )
                if cooldown_elapsed:
                    fire_alert = True
                    s.last_alert_ts = ts
                    s.verify_confirm_count = 0
                    if s.manual_mode is None:
                        new_mode = "Watch"  # per SRD 4.4: fire, then drop to Watch
                    logger.info(
                        "controller: sustained-risk alert fired (score=%.3f, ts=%.1f)", score, ts
                    )
                else:
                    # Already fired recently; keep counting suppressed so a
                    # continuously-high score doesn't re-fire every window.
                    s.verify_confirm_count = settings.confirm_windows
        else:
            s.verify_confirm_count = 0

        s.mode = new_mode
        return ControllerDecision(mode=new_mode, fire_alert=fire_alert, score=score, timestamp=ts)

    def _select_mode(self, score: float) -> Mode:
        s = self.state
        cfg = settings

        if score >= cfg.risk_alert:
            return "Verify"

        trending_up = self._is_trending_up()
        if (cfg.risk_elevated <= score < cfg.risk_alert) or trending_up:
            return "Watch"

        sqi_stable = len(s.recent_sqi) == s.recent_sqi.maxlen and all(v == 1 for v in s.recent_sqi)
        if score < cfg.risk_low and s.mode != "Verify" and self._battery_low() and sqi_stable:
            return "Eco"

        return "Normal"

    def _battery_low(self) -> bool:
        # battery_pct is passed into evaluate() and stashed there so
        # _select_mode (called from within the same evaluate() invocation)
        # can read it without threading it through every helper's signature.
        # None = source can't measure battery (USB serial); treated as
        # sufficient, so it never forces Eco (docs/API_CONTRACT.md section 2.3).
        return self._last_battery_pct is not None and self._last_battery_pct < settings.battery_eco_pct

    def _is_trending_up(self) -> bool:
        scores = list(self.state.recent_scores)
        if len(scores) < settings.watch_trend_window:
            return False
        recent = scores[-settings.watch_trend_window:]
        # Monotonic non-decreasing over the trend window, with at least some
        # real increase overall -- avoids flagging noise-level wobble as a trend.
        increasing = all(b >= a for a, b in zip(recent, recent[1:]))
        meaningful_rise = (recent[-1] - recent[0]) > 0.05
        return increasing and meaningful_rise


# --- Foot-check scheduler (SRD 4.4) -----------------------------------------


@dataclass
class FootCheckDecision:
    action: str  # "scheduled_24h" | "scheduled_8h" | "retry_1h" | "deferred_low_battery"
    next_check_scheduled: float


def schedule_next_foot_check(
    *, last_result_valid: bool, last_delta_t: Optional[float], now: Optional[float] = None
) -> FootCheckDecision:
    """Pure function implementing SRD 4.4's deterministic scheduler exactly:

        previous_check_result == "normal"   -> next_check = 24h
        previous_check_result == "elevated" -> next_check = 8h
        last_check_invalid                  -> retry in 1h

    "elevated" means delta_t exceeded the IWGDF reference threshold
    (config.foot_check_elevated_threshold_c, background citation not a
    diagnostic claim -- SRD 5.1). Called after every completed foot check to
    compute when the next one should be attempted; the battery gate is applied
    separately in `should_fire_foot_check` at the moment the scheduled time
    arrives, per SRD 4.4's "if scheduled_time_reached and battery_sufficient."
    """
    now = now if now is not None else time.time()

    if not last_result_valid:
        return FootCheckDecision(action="retry_1h", next_check_scheduled=now + settings.foot_check_invalid_retry_s)

    if is_foot_check_elevated(last_delta_t):
        return FootCheckDecision(
            action="scheduled_8h", next_check_scheduled=now + settings.foot_check_elevated_interval_s
        )
    return FootCheckDecision(
        action="scheduled_24h", next_check_scheduled=now + settings.foot_check_normal_interval_s
    )


def is_foot_check_elevated(delta_t: Optional[float]) -> Optional[bool]:
    """delta_t above the IWGDF reference threshold (background, not a
    diagnostic claim). None when there is no valid reading to judge. The one
    place this comparison lives, so the scheduler and the UI's flag agree."""
    if delta_t is None:
        return None
    return delta_t > settings.foot_check_elevated_threshold_c


def should_fire_foot_check(
    *, scheduled_time: Optional[float], battery_pct: Optional[int], now: Optional[float] = None
) -> bool:
    """SRD 4.4: 'if scheduled_time_reached and battery_sufficient: wake_auxiliary_node()'."""
    now = now if now is not None else time.time()
    if scheduled_time is None:
        return False
    # None = unmeasured (bus-powered); treated as sufficient, per API_CONTRACT 2.3.
    battery_ok = battery_pct is None or battery_pct >= settings.battery_aux_min
    return now >= scheduled_time and battery_ok
