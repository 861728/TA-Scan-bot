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


def _calc_atr(bars: list[Bar], period: int = 14) -> float | None:
    if len(bars) < 2:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        b, prev = bars[i], bars[i - 1]
        trs.append(max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close)))
    recent = trs[-period:] if len(trs) >= period else trs
    return sum(recent) / len(recent) if recent else None


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
            atr = _calc_atr(cached_bars) if cached_bars else None
            message = self._build_alert_text(
                config, summary, decision,
                ai.result.summary if ai.result else None,
                last_price, krw_price,
                results=results,
                atr=atr,
            )
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
        results: list[IndicatorResult] | None = None,
        atr: float | None = None,
    ) -> str:
        _INDICATOR_LABELS: dict[str, str] = {
            "wvf_spike": "WVF 스파이크",
            "volume_capitulation": "거래량 항복",
            "obv_divergence": "OBV 다이버전스",
            "mfi": "MFI 과매도",
            "cmf": "CMF 자금유입",
            "triple_stoch_rsi": "스토캐스틱 RSI",
            "adline_divergence": "AD라인 다이버전스",
            "composite_oscillator": "복합 오실레이터",
            "vpt": "VPT 반등",
            "nvi_pvi": "NVI/PVI 반전",
            "rsi_sma200": "RSI + 200MA",
            "bb_stochastic": "BB 스토캐스틱",
            "macd_obv_divergence": "MACD+OBV 다이버전스",
            "fibonacci_618_support": "피보나치 0.618 지지",
            "ichimoku_rsi_obv": "일목+RSI+OBV",
            "ks_reversal": "캔들 반전",
            "macd_divergence": "MACD 다이버전스",
        }

        sep = "━━━━━━━━━━━━━━━"
        lines = [
            f"🎯 {config.symbol} 바닥 시그널 · {config.timeframe}",
            sep,
        ]

        if last_price is not None:
            price_str = f"💰 현재가: ${last_price:,.2f}"
            if krw_price is not None:
                price_str += f" (₩{krw_price:,.0f})"
            lines.append(price_str)

        lines.append(f"⚡ 신호 강도: {summary.total_score}점")

        active = [r for r in (results or []) if r.score > 0]
        if active:
            lines.append("")
            lines.append("📊 핵심 근거")
            for r in active:
                label = _INDICATOR_LABELS.get(r.indicator, r.indicator)
                lines.append(f"• {label}")

        if last_price is not None and atr is not None and atr > 0:
            stop = last_price - 1.5 * atr
            target = last_price + 3.0 * atr
            stop_pct = (stop - last_price) / last_price * 100
            target_pct = (target - last_price) / last_price * 100
            rr = (target - last_price) / (last_price - stop) if last_price > stop else 0.0
            lines.append("")
            lines.append("📐 매매 기준 (ATR 기반)")
            lines.append(f"• 진입가: ${last_price:,.2f}")
            lines.append(f"• 손절가: ${stop:,.2f} ({stop_pct:+.1f}%)")
            lines.append(f"• 목표가: ${target:,.2f} ({target_pct:+.1f}%)")
            lines.append(f"• 손익비: 1:{rr:.1f}")

        if ai_summary:
            lines.append("")
            lines.append("🤖 AI 분석")
            lines.append(ai_summary)

        if decision.action == AlertAction.SEND_STRENGTHENED:
            lines.append("")
            lines.append("⬆️ 이전 대비 신호 강화")

        return "\n".join(lines)
