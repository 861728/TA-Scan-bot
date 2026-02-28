from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from .ai_layer import AIInterpreter
from .alert_engine import AlertAction, AlertDecision, AlertEngine
from .data_layer import Bar, DataCache, DataLayer, normalize_timestamp
from .indicator_engine import IndicatorEngine, IndicatorResult, SignalSummary
from .monitoring import RuntimeMetrics
from .providers import KRWConverter
from .recovery import FetchRecovery


class Notifier(Protocol):
    def send(self, text: str) -> None:
        ...


@dataclass(frozen=True)
class ScanRuntimeConfig:
    symbol: str
    timeframe: str = "15m"
    max_gap_minutes: int = 60


@dataclass(frozen=True)
class ScanCycleResult:
    timestamp: datetime
    symbol: str
    summary: SignalSummary
    alert_decision: AlertDecision
    ai_called: bool
    ai_reason: str
    data_source: str


class ScannerRuntime:
    """Phase 4 runtime orchestrator for scan → alert → AI pipeline."""

    def __init__(
        self,
        cache: DataCache,
        data_layer: DataLayer,
        recovery: FetchRecovery,
        indicator_engine: IndicatorEngine,
        alert_engine: AlertEngine,
        ai_interpreter: AIInterpreter,
        notifier: Notifier,
        metrics: RuntimeMetrics | None = None,
        krw_converter: KRWConverter | None = None,
    ) -> None:
        self.cache = cache
        self.data_layer = data_layer
        self.recovery = recovery
        self.indicator_engine = indicator_engine
        self.alert_engine = alert_engine
        self.ai_interpreter = ai_interpreter
        self.notifier = notifier
        self.metrics = metrics
        self.krw_converter = krw_converter

    def run_cycle(
        self,
        config: ScanRuntimeConfig,
        fetcher: Callable[[str, str], list[Bar]],
        now: datetime | None = None,
    ) -> ScanCycleResult:
        ts = normalize_timestamp(now or datetime.now())
        recovered = self.recovery.fetch_with_fallback(config.symbol, config.timeframe, fetcher)

        metadata = self.data_layer.update_cache(
            symbol=config.symbol,
            timeframe=config.timeframe,
            incoming_bars=recovered.bars,
            max_gap_minutes=config.max_gap_minutes,
        )
        cached_bars = self.cache.load(config.symbol, config.timeframe)

        results, summary = self.indicator_engine.run(cached_bars)
        decision = self.alert_engine.decide(config.symbol, summary, results, ts)

        ai = self.ai_interpreter.maybe_call(
            symbol=config.symbol,
            timeframe=config.timeframe,
            summary=summary,
            results=results,
            decision=decision,
            now=ts,
        )

        if decision.should_send:
            last_price = cached_bars[-1].close if cached_bars else None
            krw_price = self.krw_converter.convert(last_price) if (self.krw_converter and last_price) else None
            message = self._build_alert_text(config, summary, decision, ai.result.summary if ai.result else None, last_price, krw_price)
            self.notifier.send(message)

        if self.metrics is not None:
            self.metrics.record_cycle(
                data_source=recovered.source,
                alert_sent=decision.should_send,
                ai_called=ai.called,
            )

        return ScanCycleResult(
            timestamp=ts,
            symbol=config.symbol,
            summary=summary,
            alert_decision=decision,
            ai_called=ai.called,
            ai_reason=ai.reason,
            data_source=recovered.source,
        )

    @staticmethod
    def _build_alert_text(
        config: ScanRuntimeConfig,
        summary: SignalSummary,
        decision: AlertDecision,
        ai_summary: str | None,
        last_price: float | None = None,
        krw_price: float | None = None,
    ) -> str:
        lines = [f"[M7 바닥 스캐너] {config.symbol} / {config.timeframe}"]
        if last_price is not None:
            price_str = f"현재가: ${last_price:,.2f}"
            if krw_price is not None:
                price_str += f" (₩{krw_price:,.0f})"
            lines.append(price_str)
        lines.append(f"신호 점수: {summary.total_score}점  방향: {summary.strongest_signal.value}")
        if decision.action == AlertAction.SEND_STRENGTHENED:
            lines.append("※ 신호 강화 (이전 대비 점수 상승)")
        if ai_summary:
            lines.append(f"\nAI 해석: {ai_summary}")
        return "\n".join(lines)
