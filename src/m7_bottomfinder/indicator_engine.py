from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from .data_layer import Bar, normalize_timestamp


class SignalDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class IndicatorResult:
    indicator: str
    signal: SignalDirection
    score: int
    evidence: str
    raw_values: dict[str, float | int | bool | str | None]
    timestamp: datetime

    @staticmethod
    def neutral(indicator: str, timestamp: datetime, evidence: str, raw_values: dict[str, float | int | bool | str | None] | None = None) -> "IndicatorResult":
        return IndicatorResult(
            indicator=indicator,
            signal=SignalDirection.NEUTRAL,
            score=0,
            evidence=evidence,
            raw_values=raw_values or {},
            timestamp=normalize_timestamp(timestamp),
        )


class Indicator(Protocol):
    name: str
    weight: int

    def evaluate(self, bars: list[Bar]) -> IndicatorResult:
        ...


class BaseIndicator:
    name: str = "base"
    weight: int = 1

    def evaluate(self, bars: list[Bar]) -> IndicatorResult:
        if not bars:
            raise ValueError(f"{self.name} requires bars")
        result = self._evaluate(bars)
        if result.indicator != self.name:
            raise ValueError("indicator mismatch")
        if result.signal == SignalDirection.NEUTRAL and result.score != 0:
            raise ValueError("neutral must have zero score")
        if result.score < 0 or result.score > self.weight:
            raise ValueError("score out of range")
        return result

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        raise NotImplementedError


@dataclass(frozen=True)
class SignalSummary:
    total_score: int
    strongest_signal: SignalDirection
    bullish_count: int
    bearish_count: int
    neutral_count: int
    should_alert: bool
    should_call_ai: bool
    s_tier_hits: int
    track: int = 1  # 1 = 바닥반등, 2 = 눌림목


class IndicatorEngine:
    def __init__(
        self,
        indicators: list[Indicator],
        track1_threshold: int = 4,
        track2_threshold: int = 5,
        ai_call_threshold: int = 6,
        min_s_hits_for_ai: int = 2,
        s_tier_names: set[str] | None = None,
        track1_symbols: list[str] | None = None,
        track2_symbols: list[str] | None = None,
    ) -> None:
        self.indicators = indicators
        self.track1_threshold = track1_threshold
        self.track2_threshold = track2_threshold
        self.ai_call_threshold = ai_call_threshold
        self.min_s_hits_for_ai = min_s_hits_for_ai
        self.s_tier_names = s_tier_names or set()
        self.track1_symbols: set[str] = set(track1_symbols or [])
        self.track2_symbols: set[str] = set(track2_symbols or [])

    def run(self, bars: list[Bar], symbol: str = "") -> tuple[list[IndicatorResult], SignalSummary]:
        # lazy import to avoid circular dependency (indicators.py imports from indicator_engine.py)
        from .indicators import calculate_score, calculate_track2_score

        results = [indicator.evaluate(bars) for indicator in self.indicators]
        bullish = sum(1 for r in results if r.signal == SignalDirection.BULLISH)
        bearish = sum(1 for r in results if r.signal == SignalDirection.BEARISH)
        neutral = len(results) - bullish - bearish

        track = 2 if symbol in self.track2_symbols else 1
        composite = calculate_track2_score(bars) if track == 2 else calculate_score(bars)
        threshold = self.track2_threshold if track == 2 else self.track1_threshold
        should_alert = composite >= threshold

        s_hits = sum(1 for r in results if r.indicator in self.s_tier_names and r.score > 0)
        summary = SignalSummary(
            total_score=composite,
            strongest_signal=SignalDirection.BULLISH if composite > 0 else SignalDirection.NEUTRAL,
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            should_alert=should_alert,
            should_call_ai=should_alert and (composite >= self.ai_call_threshold or s_hits >= self.min_s_hits_for_ai),
            s_tier_hits=s_hits,
            track=track,
        )
        return results, summary
