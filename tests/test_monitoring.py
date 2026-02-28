from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from m7_bottomfinder.app import ScanAppConfig, ScanApplication
from m7_bottomfinder.data_layer import Bar
from m7_bottomfinder.monitoring import RuntimeMetrics

UTC = ZoneInfo("UTC")


def make_bars(n: int = 80) -> list[Bar]:
    base = datetime(2026, 2, 1, tzinfo=UTC)
    bars: list[Bar] = []
    close = 120.0
    for i in range(n):
        close -= 0.1
        bars.append(
            Bar(
                timestamp=base + timedelta(minutes=15 * i),
                open=close + 0.2,
                high=close + 0.8,
                low=close - 0.8,
                close=close,
                volume=1000.0,
            )
        )
    return bars


def test_runtime_metrics_record_cycle() -> None:
    m = RuntimeMetrics()
    m.record_cycle(data_source="provider", alert_sent=True, ai_called=False)
    m.record_cycle(data_source="cache", alert_sent=False, ai_called=True)
    s = m.snapshot()
    assert s.cycles_total == 2
    assert s.alerts_sent == 1
    assert s.ai_calls == 1
    assert s.provider_source_count == 1
    assert s.cache_source_count == 1


def test_application_exposes_metrics_snapshot(tmp_path) -> None:
    cfg = ScanAppConfig(
        symbols=["AAPL"],
        timeframe="15m",
        interval_seconds=1,
        cache_dir=str(tmp_path / "cache"),
        score_threshold=1,
        ai_call_threshold=2,
        min_s_hits_for_ai=1,
        cooldown_minutes=0,
        strengthen_delta=3,
        ai_per_symbol_daily=3,
        ai_global_daily=20,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )
    app = ScanApplication(cfg)

    bars = make_bars()

    def fetcher(_symbol: str, _timeframe: str) -> list[Bar]:
        return bars

    app.run_once(fetcher)
    snap = app.get_metrics_snapshot()
    assert snap.cycles_total == 1
