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


class IndicatorEngine:
    def __init__(
        self,
        indicators: list[Indicator],
        score_threshold: int = 5,
        ai_call_threshold: int = 6,
        min_s_hits_for_ai: int = 2,
        s_tier_names: set[str] | None = None,
    ) -> None:
        self.indicators = indicators
        self.score_threshold = score_threshold
        self.ai_call_threshold = ai_call_threshold
        self.min_s_hits_for_ai = min_s_hits_for_ai
        self.s_tier_names = s_tier_names or set()

    def run(self, bars: list[Bar]) -> tuple[list[IndicatorResult], SignalSummary]:
        results = [indicator.evaluate(bars) for indicator in self.indicators]
        bullish = sum(1 for r in results if r.signal == SignalDirection.BULLISH)
        bearish = sum(1 for r in results if r.signal == SignalDirection.BEARISH)
        neutral = len(results) - bullish - bearish
        total_score = sum(r.score for r in results)

        strongest = SignalDirection.NEUTRAL
        if bullish > bearish:
            strongest = SignalDirection.BULLISH
        elif bearish > bullish:
            strongest = SignalDirection.BEARISH

        s_hits = sum(1 for r in results if r.indicator in self.s_tier_names and r.score > 0)
        summary = SignalSummary(
            total_score=total_score,
            strongest_signal=strongest,
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            should_alert=total_score >= self.score_threshold,
            should_call_ai=(total_score >= self.ai_call_threshold or s_hits >= self.min_s_hits_for_ai),
            s_tier_hits=s_hits,
        )
        return results, summary
