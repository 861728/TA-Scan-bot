from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from m7_bottomfinder.backtest import BacktestSimulator, summarize_kpi
from m7_bottomfinder.data_layer import Bar
from m7_bottomfinder.indicator_engine import IndicatorEngine
from m7_bottomfinder.indicators import MFIIndicator, WVFIndicator

UTC = ZoneInfo("UTC")


def make_bars(n: int = 260) -> list[Bar]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = 140.0
    for i in range(n):
        # first downtrend then recovery regime
        if i < 160:
            price -= 0.22
        else:
            price += 0.28

        vol = 1000.0
        if i % 40 == 0:
            vol = 3500.0

        bars.append(
            Bar(
                timestamp=base + timedelta(minutes=15 * i),
                open=price + 0.3,
                high=price + 1.1,
                low=price - 1.1,
                close=price,
                volume=vol,
            )
        )
    return bars


def test_backtest_generates_signals_and_report() -> None:
    bars = make_bars()
    engine = IndicatorEngine(
        indicators=[WVFIndicator(), MFIIndicator()],
        score_threshold=1,
        ai_call_threshold=2,
        min_s_hits_for_ai=1,
        s_tier_names={"wvf_spike"},
    )
    sim = BacktestSimulator(
        engine=engine,
        cooldown_bars=8,
        strengthen_delta=2,
        precision_target_pct=3.0,
        lookahead_bars=50,
    )

    signals, trades, report = sim.run(bars, warmup_bars=40)

    assert len(signals) > 0
    assert len(trades) == len(signals)
    assert report.signal_count == len(signals)
    assert 0.0 <= report.precision <= 1.0


def test_summarize_kpi_shape() -> None:
    bars = make_bars()
    engine = IndicatorEngine(indicators=[WVFIndicator()], score_threshold=1)
    sim = BacktestSimulator(engine=engine, lookahead_bars=20)

    _, _, report = sim.run(bars, warmup_bars=30)
    kpi = summarize_kpi(report)

    assert set(kpi.keys()) == {
        "signal_count",
        "precision",
        "avg_rebound_pct",
        "max_drawdown_pct",
        "avg_signal_duration_bars",
        "signal_to_noise_ratio",
        "avg_time_to_recovery_bars",
    }
