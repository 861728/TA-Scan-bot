from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .data_layer import Bar, normalize_timestamp
from .indicator_engine import IndicatorEngine, IndicatorResult, SignalDirection, SignalSummary


@dataclass(frozen=True)
class BacktestSignal:
    timestamp: datetime
    index: int
    score: int
    direction: SignalDirection
    indicators: tuple[str, ...]


@dataclass(frozen=True)
class BacktestTradeResult:
    signal: BacktestSignal
    entry_price: float
    max_drawdown_pct: float
    rebound_pct: float
    hit_precision_target: bool
    time_to_recovery_bars: int | None


@dataclass(frozen=True)
class BacktestReport:
    signal_count: int
    precision: float
    avg_rebound_pct: float
    max_drawdown_pct: float
    avg_signal_duration_bars: float
    signal_to_noise_ratio: float
    avg_time_to_recovery_bars: float | None


class BacktestSimulator:
    """Simple bar-by-bar simulator for Phase 1.5 KPI estimation."""

    def __init__(
        self,
        engine: IndicatorEngine,
        cooldown_bars: int = 8,
        strengthen_delta: int = 3,
        precision_target_pct: float = 3.0,
        lookahead_bars: int = 130,
    ) -> None:
        self.engine = engine
        self.cooldown_bars = cooldown_bars
        self.strengthen_delta = strengthen_delta
        self.precision_target_pct = precision_target_pct
        self.lookahead_bars = lookahead_bars

    def run(self, bars: list[Bar], warmup_bars: int = 60) -> tuple[list[BacktestSignal], list[BacktestTradeResult], BacktestReport]:
        signals = self.generate_signals(bars=bars, warmup_bars=warmup_bars)
        results = [self.evaluate_signal(s, bars) for s in signals]
        report = self._build_report(results)
        return signals, results, report

    def generate_signals(self, bars: list[Bar], warmup_bars: int = 60) -> list[BacktestSignal]:
        if len(bars) <= warmup_bars:
            return []

        signals: list[BacktestSignal] = []
        last_index_by_direction: dict[SignalDirection, int] = {}
        last_score_by_direction: dict[SignalDirection, int] = {}

        for idx in range(warmup_bars, len(bars)):
            window = bars[: idx + 1]
            results, summary = self.engine.run(window)
            direction = summary.strongest_signal
            if not summary.should_alert or direction == SignalDirection.NEUTRAL:
                continue

            prev_idx = last_index_by_direction.get(direction)
            prev_score = last_score_by_direction.get(direction, -10**9)
            in_cooldown = prev_idx is not None and (idx - prev_idx) < self.cooldown_bars
            strengthened = summary.total_score >= (prev_score + self.strengthen_delta)

            if in_cooldown and not strengthened:
                continue

            indicators = tuple(sorted(r.indicator for r in results if r.signal == direction and r.score > 0))
            sig = BacktestSignal(
                timestamp=normalize_timestamp(window[-1].timestamp),
                index=idx,
                score=summary.total_score,
                direction=direction,
                indicators=indicators,
            )
            signals.append(sig)
            last_index_by_direction[direction] = idx
            last_score_by_direction[direction] = summary.total_score

        return signals

    def evaluate_signal(self, signal: BacktestSignal, bars: list[Bar]) -> BacktestTradeResult:
        entry = bars[signal.index].close
        end = min(len(bars), signal.index + self.lookahead_bars + 1)
        future = bars[signal.index + 1 : end]
        if not future:
            return BacktestTradeResult(signal, entry, 0.0, 0.0, False, None)

        lows = [b.low for b in future]
        highs = [b.high for b in future]

        min_low = min(lows)
        max_high = max(highs)
        mdd = ((min_low - entry) / entry) * 100 if entry else 0.0
        rebound = ((max_high - entry) / entry) * 100 if entry else 0.0
        hit = rebound >= self.precision_target_pct

        ttr: int | None = None
        for i, b in enumerate(future, start=1):
            if b.high >= entry:
                ttr = i
                break

        return BacktestTradeResult(
            signal=signal,
            entry_price=entry,
            max_drawdown_pct=mdd,
            rebound_pct=rebound,
            hit_precision_target=hit,
            time_to_recovery_bars=ttr,
        )

    def _build_report(self, results: list[BacktestTradeResult]) -> BacktestReport:
        if not results:
            return BacktestReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, None)

        hit_count = sum(1 for r in results if r.hit_precision_target)
        precision = hit_count / len(results)
        avg_rebound = sum(r.rebound_pct for r in results) / len(results)
        worst_mdd = min(r.max_drawdown_pct for r in results)

        recovery_values = [r.time_to_recovery_bars for r in results if r.time_to_recovery_bars is not None]
        avg_ttr = (sum(recovery_values) / len(recovery_values)) if recovery_values else None

        # Signal duration proxy: bars to recovery if available, else full lookahead
        durations = [r.time_to_recovery_bars or self.lookahead_bars for r in results]
        avg_duration = sum(durations) / len(durations)

        # SNR proxy: precision hits to misses
        misses = len(results) - hit_count
        snr = float(hit_count) / misses if misses > 0 else float(hit_count)

        return BacktestReport(
            signal_count=len(results),
            precision=precision,
            avg_rebound_pct=avg_rebound,
            max_drawdown_pct=worst_mdd,
            avg_signal_duration_bars=avg_duration,
            signal_to_noise_ratio=snr,
            avg_time_to_recovery_bars=avg_ttr,
        )


def summarize_kpi(report: BacktestReport) -> dict[str, float | int | None]:
    return {
        "signal_count": report.signal_count,
        "precision": round(report.precision, 4),
        "avg_rebound_pct": round(report.avg_rebound_pct, 4),
        "max_drawdown_pct": round(report.max_drawdown_pct, 4),
        "avg_signal_duration_bars": round(report.avg_signal_duration_bars, 4),
        "signal_to_noise_ratio": round(report.signal_to_noise_ratio, 4),
        "avg_time_to_recovery_bars": None if report.avg_time_to_recovery_bars is None else round(report.avg_time_to_recovery_bars, 4),
    }


def extract_active_results(results: list[IndicatorResult], summary: SignalSummary) -> list[IndicatorResult]:
    direction = summary.strongest_signal
    return [r for r in results if r.signal == direction and r.score > 0]
