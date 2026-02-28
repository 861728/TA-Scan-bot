from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .data_layer import normalize_timestamp
from .indicator_engine import IndicatorResult, SignalDirection, SignalSummary


class AlertAction(str, Enum):
    SEND = "send"
    SEND_STRENGTHENED = "send_strengthened"
    SUPPRESS_NO_SIGNAL = "suppress_no_signal"
    SUPPRESS_COOLDOWN = "suppress_cooldown"
    SUPPRESS_DUPLICATE = "suppress_duplicate"


@dataclass(frozen=True)
class AlertDecision:
    action: AlertAction
    should_send: bool
    reason: str
    symbol: str
    direction: SignalDirection
    score: int
    cooldown_remaining_minutes: int | None = None


@dataclass(frozen=True)
class AlertRecord:
    symbol: str
    direction: SignalDirection
    score: int
    timestamp: datetime
    signature: str


class AlertEngine:
    def __init__(self, cooldown_minutes: int = 120, strengthened_delta: int = 3) -> None:
        self.cooldown_minutes = cooldown_minutes
        self.strengthened_delta = strengthened_delta
        self._last: dict[tuple[str, SignalDirection], AlertRecord] = {}

    def decide(
        self,
        symbol: str,
        summary: SignalSummary,
        results: list[IndicatorResult],
        now: datetime | None = None,
    ) -> AlertDecision:
        ts = normalize_timestamp(now or datetime.now())
        direction = summary.strongest_signal

        if not summary.should_alert or direction == SignalDirection.NEUTRAL:
            return AlertDecision(AlertAction.SUPPRESS_NO_SIGNAL, False, "threshold/direction unmet", symbol, direction, summary.total_score)

        key = (symbol, direction)
        signature = self._signature(results, direction)
        prev = self._last.get(key)
        if prev:
            elapsed = ts - prev.timestamp
            if elapsed < timedelta(minutes=self.cooldown_minutes):
                if summary.total_score >= prev.score + self.strengthened_delta:
                    self._last[key] = AlertRecord(symbol, direction, summary.total_score, ts, signature)
                    return AlertDecision(AlertAction.SEND_STRENGTHENED, True, "strengthened in cooldown", symbol, direction, summary.total_score, 0)
                remaining = int((timedelta(minutes=self.cooldown_minutes) - elapsed).total_seconds() // 60)
                return AlertDecision(AlertAction.SUPPRESS_COOLDOWN, False, "cooldown", symbol, direction, summary.total_score, max(remaining, 0))

            if prev.signature == signature and prev.score == summary.total_score:
                return AlertDecision(AlertAction.SUPPRESS_DUPLICATE, False, "duplicate", symbol, direction, summary.total_score)

        self._last[key] = AlertRecord(symbol, direction, summary.total_score, ts, signature)
        return AlertDecision(AlertAction.SEND, True, "accepted", symbol, direction, summary.total_score)

    @staticmethod
    def _signature(results: list[IndicatorResult], direction: SignalDirection) -> str:
        names = sorted(r.indicator for r in results if r.signal == direction and r.score > 0)
        return "|".join(names)
