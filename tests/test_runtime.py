from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from m7_bottomfinder.ai_layer import AIInterpreter, AIUsageLimiter, RuleBasedProvider
from m7_bottomfinder.alert_engine import AlertAction, AlertEngine
from m7_bottomfinder.data_layer import Bar, DataCache, DataLayer
from m7_bottomfinder.indicator_engine import BaseIndicator, IndicatorEngine, IndicatorResult, SignalDirection
from m7_bottomfinder.recovery import FetchRecovery
from m7_bottomfinder.runtime import ScanRuntimeConfig, ScannerRuntime

UTC = ZoneInfo("UTC")


class DummyBullishIndicator(BaseIndicator):
    name = "dummy_s"
    weight = 6

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        return IndicatorResult(
            indicator=self.name,
            signal=SignalDirection.BULLISH,
            score=6,
            evidence="forced bullish",
            raw_values={"x": 1},
            timestamp=bars[-1].timestamp,
        )


class MemoryNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


def make_bars(n: int = 100) -> list[Bar]:
    base = datetime(2026, 2, 1, tzinfo=UTC)
    bars: list[Bar] = []
    close = 100.0
    for i in range(n):
        close += 0.1
        bars.append(
            Bar(
                timestamp=base + timedelta(minutes=15 * i),
                open=close - 0.2,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1000.0,
            )
        )
    return bars


def test_runtime_cycle_sends_alert_and_ai_summary(tmp_path) -> None:
    cache = DataCache(tmp_path)
    layer = DataLayer(cache)
    recovery = FetchRecovery(cache)
    indicator_engine = IndicatorEngine([DummyBullishIndicator()], score_threshold=5, ai_call_threshold=6, min_s_hits_for_ai=1, s_tier_names={"dummy_s"})
    alert_engine = AlertEngine(cooldown_minutes=0)
    ai = AIInterpreter(RuleBasedProvider(), AIUsageLimiter(per_symbol=3, global_daily=20))
    notifier = MemoryNotifier()

    runtime = ScannerRuntime(cache, layer, recovery, indicator_engine, alert_engine, ai, notifier)

    bars = make_bars()

    def fetcher(_symbol: str, _timeframe: str) -> list[Bar]:
        return bars

    result = runtime.run_cycle(ScanRuntimeConfig(symbol="AAPL", timeframe="15m"), fetcher, datetime(2026, 2, 2, tzinfo=UTC))

    assert result.alert_decision.action in {AlertAction.SEND, AlertAction.SEND_STRENGTHENED}
    assert result.ai_called is True
    assert len(notifier.messages) == 1
    assert "AI:" in notifier.messages[0]


def test_runtime_cycle_uses_cache_fallback(tmp_path) -> None:
    cache = DataCache(tmp_path)
    bars = make_bars(10)
    cache.save("AAPL", "15m", bars)

    layer = DataLayer(cache)
    recovery = FetchRecovery(cache)
    indicator_engine = IndicatorEngine([DummyBullishIndicator()], score_threshold=5, ai_call_threshold=6, min_s_hits_for_ai=1, s_tier_names={"dummy_s"})
    alert_engine = AlertEngine(cooldown_minutes=0)
    ai = AIInterpreter(RuleBasedProvider(), AIUsageLimiter())
    notifier = MemoryNotifier()

    runtime = ScannerRuntime(cache, layer, recovery, indicator_engine, alert_engine, ai, notifier)

    def broken_fetcher(_symbol: str, _timeframe: str) -> list[Bar]:
        raise RuntimeError("down")

    result = runtime.run_cycle(ScanRuntimeConfig(symbol="AAPL", timeframe="15m"), broken_fetcher)
    assert result.data_source == "cache"
