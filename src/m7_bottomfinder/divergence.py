from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .data_layer import normalize_timestamp


class DivergenceType(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NONE = "none"


@dataclass(frozen=True)
class Pivot:
    index: int
    value: float
    timestamp: datetime | None = None


@dataclass(frozen=True)
class DivergenceSignal:
    found: bool
    kind: DivergenceType
    evidence: str
    price: tuple[Pivot, Pivot] | None
    indicator: tuple[Pivot, Pivot] | None


class DivergenceDetector:
    def __init__(self, pivot_window: int = 1) -> None:
        if pivot_window < 1:
            raise ValueError("pivot_window must be >=1")
        self.pivot_window = pivot_window

    def _find_pivots(self, values: list[float], mode: str) -> list[int]:
        pivots: list[int] = []
        w = self.pivot_window
        for i in range(w, len(values) - w):
            c = values[i]
            left = values[i - w : i]
            right = values[i + 1 : i + w + 1]
            if mode == "low" and c < min(left) and c < min(right):
                pivots.append(i)
            if mode == "high" and c > max(left) and c > max(right):
                pivots.append(i)
        return pivots

    def detect(self, prices: list[float], indicators: list[float], timestamps: list[datetime] | None = None) -> DivergenceSignal:
        if len(prices) != len(indicators):
            raise ValueError("length mismatch")
        if len(prices) < (2 * self.pivot_window + 3):
            return DivergenceSignal(False, DivergenceType.NONE, "not enough data", None, None)

        lows = self._find_pivots(prices, "low")
        if len(lows) >= 2:
            p1, p2 = lows[-2], lows[-1]
            if prices[p2] < prices[p1] and indicators[p2] > indicators[p1]:
                return DivergenceSignal(
                    True,
                    DivergenceType.BULLISH,
                    "price LL + indicator HL",
                    (self._pivot(prices, timestamps, p1), self._pivot(prices, timestamps, p2)),
                    (self._pivot(indicators, timestamps, p1), self._pivot(indicators, timestamps, p2)),
                )

        highs = self._find_pivots(prices, "high")
        if len(highs) >= 2:
            p1, p2 = highs[-2], highs[-1]
            if prices[p2] > prices[p1] and indicators[p2] < indicators[p1]:
                return DivergenceSignal(
                    True,
                    DivergenceType.BEARISH,
                    "price HH + indicator LH",
                    (self._pivot(prices, timestamps, p1), self._pivot(prices, timestamps, p2)),
                    (self._pivot(indicators, timestamps, p1), self._pivot(indicators, timestamps, p2)),
                )

        return DivergenceSignal(False, DivergenceType.NONE, "no divergence", None, None)

    @staticmethod
    def _pivot(values: list[float], timestamps: list[datetime] | None, idx: int) -> Pivot:
        ts = normalize_timestamp(timestamps[idx]) if timestamps else None
        return Pivot(index=idx, value=float(values[idx]), timestamp=ts)
