from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from m7_bottomfinder.data_layer import Bar
from m7_bottomfinder.divergence import DivergenceDetector, DivergenceType
from m7_bottomfinder.indicator_engine import IndicatorEngine, SignalDirection
from m7_bottomfinder.indicators import (
    MFIIndicator,
    OBVDivergenceIndicator,
    VolumeCapitulationIndicator,
    WVFIndicator,
    default_phase2_indicators,
)

UTC = ZoneInfo("UTC")


def make_bars(n: int = 220) -> list[Bar]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = 100.0
    for i in range(n):
        # gentle downtrend then rebound with final capitulation bar
        if i < n - 10:
            price -= 0.1
        else:
            price += 0.35
        bars.append(
            Bar(
                timestamp=base + timedelta(minutes=15 * i),
                open=price + 0.2,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=1000.0 if i < n - 1 else 5000.0,
            )
        )
    return bars


def test_divergence_detector_bullish() -> None:
    detector = DivergenceDetector(pivot_window=1)
    prices = [10, 8, 9, 7, 8, 9]
    obv_like = [100, 80, 85, 90, 91, 92]
    signal = detector.detect(prices, obv_like)
    assert signal.found is True
    assert signal.kind == DivergenceType.BULLISH


def test_engine_runs_phase2_bundle() -> None:
    bars = make_bars()
    indicators = default_phase2_indicators()
    engine = IndicatorEngine(
        indicators=indicators,
        score_threshold=5,
        ai_call_threshold=6,
        min_s_hits_for_ai=2,
        s_tier_names={"wvf_spike", "volume_capitulation", "obv_divergence"},
    )
    results, summary = engine.run(bars)
    assert len(results) == len(indicators)
    assert summary.total_score >= 0
    assert summary.strongest_signal in {SignalDirection.BULLISH, SignalDirection.BEARISH, SignalDirection.NEUTRAL}


def test_wvf_and_volume_capitulation_emit_numeric_evidence() -> None:
    bars = make_bars()
    wvf = WVFIndicator().evaluate(bars)
    cap = VolumeCapitulationIndicator().evaluate(bars)
    assert "wvf" in wvf.raw_values
    assert "volume" in cap.raw_values


def test_obv_divergence_and_mfi_return_contract_shape() -> None:
    bars = make_bars()
    obv = OBVDivergenceIndicator().evaluate(bars)
    mfi = MFIIndicator().evaluate(bars)
    assert obv.indicator == "obv_divergence"
    assert isinstance(obv.raw_values, dict)
    assert mfi.indicator == "mfi"
    assert "mfi" in mfi.raw_values
