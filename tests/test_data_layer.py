from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from m7_bottomfinder.data_layer import Bar, DataCache, DataLayer, normalize_timestamp

UTC = ZoneInfo("UTC")
KST = ZoneInfo("Asia/Seoul")


def bar(ts: datetime, close: float, volume: float = 100.0) -> Bar:
    return Bar(
        timestamp=ts,
        open=close - 0.5,
        high=close + 0.5,
        low=close - 1.0,
        close=close,
        volume=volume,
    )


def test_normalize_timestamp_to_utc() -> None:
    local = datetime(2026, 2, 1, 9, 0, tzinfo=KST)
    normalized = normalize_timestamp(local)
    assert normalized.tzinfo == UTC
    assert normalized.hour == 0


def test_merge_incremental_prefers_latest_same_timestamp(tmp_path) -> None:
    layer = DataLayer(cache=DataCache(tmp_path))
    t0 = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)

    existing = [bar(t0, 100.0)]
    incoming = [bar(t0, 101.0), bar(t0 + timedelta(minutes=15), 102.0)]

    merged = layer.merge_incremental(existing=existing, incoming=incoming)
    assert len(merged) == 2
    assert merged[0].close == 101.0
    assert merged[1].close == 102.0


def test_fill_missing_inserts_carry_forward_bar(tmp_path) -> None:
    layer = DataLayer(cache=DataCache(tmp_path))
    t0 = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
    t2 = t0 + timedelta(minutes=30)

    repaired = layer.fill_missing([bar(t0, 100.0), bar(t2, 103.0)], max_gap_minutes=60)
    assert len(repaired) == 3
    assert repaired[1].timestamp == t0 + timedelta(minutes=15)
    assert repaired[1].close == 100.0
    assert repaired[1].volume == 0.0


def test_update_cache_round_trip(tmp_path) -> None:
    cache = DataCache(tmp_path)
    layer = DataLayer(cache=cache)
    t0 = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)

    metadata = layer.update_cache(
        symbol="AAPL",
        timeframe="15m",
        incoming_bars=[bar(t0, 100.0), bar(t0 + timedelta(minutes=15), 101.0)],
    )

    assert metadata.symbol == "AAPL"
    assert metadata.timeframe == "15m"
    assert metadata.bar_count == 2

    loaded = cache.load("AAPL", "15m")
    assert len(loaded) == 2
    assert loaded[0].timestamp.tzinfo == UTC
