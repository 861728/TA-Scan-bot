from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from m7_bottomfinder.ai_layer import AIInterpreter, AIUsageLimiter, RuleBasedProvider
from m7_bottomfinder.alert_engine import AlertAction, AlertEngine
from m7_bottomfinder.data_layer import Bar, DataCache
from m7_bottomfinder.indicator_engine import IndicatorEngine, SignalDirection
from m7_bottomfinder.indicators import MFIIndicator, WVFIndicator
from m7_bottomfinder.recovery import FetchRecovery

UTC = ZoneInfo("UTC")


def make_bars(n: int = 120) -> list[Bar]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = 100.0
    for i in range(n):
        price = price - 0.2 if i < n - 1 else price + 0.1
        bars.append(
            Bar(
                timestamp=base + timedelta(minutes=15 * i),
                open=price + 0.1,
                high=price + 0.8,
                low=price - 0.8,
                close=price,
                volume=1000.0 if i < n - 1 else 4000.0,
            )
        )
    return bars


def test_alert_engine_cooldown_and_strengthened() -> None:
    bars = make_bars()
    engine = IndicatorEngine([WVFIndicator(), MFIIndicator()], score_threshold=1, ai_call_threshold=2, min_s_hits_for_ai=1, s_tier_names={"wvf_spike"})
    results, summary = engine.run(bars)
    a = AlertEngine(cooldown_minutes=120, strengthened_delta=3)
    now = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)

    first = a.decide("AAPL", summary, results, now)
    second = a.decide("AAPL", summary, results, now + timedelta(minutes=30))

    assert first.action in {AlertAction.SEND, AlertAction.SUPPRESS_NO_SIGNAL}
    if first.should_send:
        assert second.action in {AlertAction.SUPPRESS_COOLDOWN, AlertAction.SEND_STRENGTHENED}


def test_ai_interpreter_gate_and_limit() -> None:
    bars = make_bars()
    engine = IndicatorEngine([WVFIndicator()], score_threshold=1, ai_call_threshold=1, min_s_hits_for_ai=1, s_tier_names={"wvf_spike"})
    results, summary = engine.run(bars)
    decision = AlertEngine(cooldown_minutes=0).decide("AAPL", summary, results, datetime(2026, 2, 1, tzinfo=UTC))

    ai = AIInterpreter(RuleBasedProvider(), AIUsageLimiter(per_symbol=1, global_daily=2))
    first = ai.maybe_call("AAPL", "15m", summary, results, decision, datetime(2026, 2, 1, tzinfo=UTC))
    second = ai.maybe_call("AAPL", "15m", summary, results, decision, datetime(2026, 2, 1, 0, 30, tzinfo=UTC))

    if first.called:
        assert second.called is False


def test_recovery_falls_back_to_cache(tmp_path) -> None:
    cache = DataCache(tmp_path)
    bars = make_bars(5)
    cache.save("AAPL", "15m", bars)

    recovery = FetchRecovery(cache)

    def broken(_symbol: str, _timeframe: str) -> list[Bar]:
        raise RuntimeError("provider error")

    result = recovery.fetch_with_fallback("AAPL", "15m", broken)
    assert result.source == "cache"
    assert len(result.bars) == 5
