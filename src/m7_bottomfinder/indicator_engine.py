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
class IndicatorGroup:
    name: str
    members: frozenset[str]
    cap: int


@dataclass(frozen=True)
class SignalSummary:
    total_score: int
    grouped_score: int
    strongest_signal: SignalDirection
    bullish_count: int
    bearish_count: int
    neutral_count: int
    should_alert: bool
    should_call_ai: bool
    s_tier_hits: int
    volume_ok: bool = True


class IndicatorEngine:
    def __init__(
        self,
        indicators: list[Indicator],
        score_threshold: int = 5,
        ai_call_threshold: int = 6,
        min_s_hits_for_ai: int = 2,
        s_tier_names: set[str] | None = None,
        groups: list[IndicatorGroup] | None = None,
        min_volume_multiple: float = 1.5,
    ) -> None:
        self.indicators = indicators
        self.score_threshold = score_threshold
        self.ai_call_threshold = ai_call_threshold
        self.min_s_hits_for_ai = min_s_hits_for_ai
        self.s_tier_names = s_tier_names or set()
        self.groups = groups or []
        self.min_volume_multiple = min_volume_multiple

    def run(self, bars: list[Bar]) -> tuple[list[IndicatorResult], SignalSummary]:
        results = [indicator.evaluate(bars) for indicator in self.indicators]
        bullish = sum(1 for r in results if r.signal == SignalDirection.BULLISH)
        bearish = sum(1 for r in results if r.signal == SignalDirection.BEARISH)
        neutral = len(results) - bullish - bearish

        strongest = SignalDirection.NEUTRAL
        if bullish > bearish:
            strongest = SignalDirection.BULLISH
        elif bearish > bullish:
            strongest = SignalDirection.BEARISH

        s_hits = sum(1 for r in results if r.indicator in self.s_tier_names and r.score > 0)

        # --- Grouped scoring ---
        score_by_indicator: dict[str, int] = {r.indicator: r.score for r in results}
        grouped_members: set[str] = set()
        grouped_score = 0

        for group in self.groups:
            raw = sum(score_by_indicator.get(m, 0) for m in group.members)
            grouped_score += min(raw, group.cap)
            grouped_members |= group.members

        for r in results:
            if r.indicator not in grouped_members:
                grouped_score += r.score

        # --- Volume filter ---
        vol_result = next(
            (r for r in results if r.indicator == "volume_capitulation"), None
        )
        volume_ok = True
        if vol_result is not None and self.min_volume_multiple > 0:
            vol = vol_result.raw_values.get("volume", 0.0)
            avg = vol_result.raw_values.get("avg", 0.0)
            if avg and float(avg) > 0:
                volume_ok = float(vol) >= self.min_volume_multiple * float(avg)

        summary = SignalSummary(
            total_score=sum(r.score for r in results),
            grouped_score=grouped_score,
            strongest_signal=strongest,
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            should_alert=(grouped_score >= self.score_threshold) and volume_ok,
            should_call_ai=(grouped_score >= self.ai_call_threshold or s_hits >= self.min_s_hits_for_ai),
            s_tier_hits=s_hits,
            volume_ok=volume_ok,
        )
        return results, summary
