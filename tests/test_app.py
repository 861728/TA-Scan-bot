from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from m7_bottomfinder.app import ScanAppConfig, ScanApplication
from m7_bottomfinder.data_layer import Bar

UTC = ZoneInfo("UTC")


class CaptureNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


def make_bars(n: int = 200) -> list[Bar]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    close = 200.0
    for i in range(n):
        close -= 0.15
        vol = 1000.0 if i < n - 1 else 5000.0
        bars.append(
            Bar(
                timestamp=base + timedelta(minutes=15 * i),
                open=close + 0.2,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=vol,
            )
        )
    return bars


def test_config_loads_from_toml(tmp_path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[runtime]
symbols=["AAPL","TSLA"]
timeframe="15m"
interval_seconds=60
cache_dir="data/testcache"

[scoring]
score_threshold=5
ai_call_threshold=6
min_s_hits_for_ai=2

[alerts]
cooldown_minutes=120
strengthen_delta=3

[ai]
per_symbol_daily=3
global_daily=20
""",
        encoding="utf-8",
    )

    cfg = ScanAppConfig.from_toml(cfg_path)
    assert cfg.symbols == ["AAPL", "TSLA"]
    assert cfg.timeframe == "15m"
    assert cfg.interval_seconds == 60


def test_application_run_once_executes_cycle(tmp_path) -> None:
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
    )
    notifier = CaptureNotifier()
    app = ScanApplication(cfg, notifier=notifier)

    bars = make_bars()

    def fetcher(_symbol: str, _timeframe: str) -> list[Bar]:
        return bars

    app.run_once(fetcher)
    # Message may be absent depending on signal, but run_once should complete without error and cache should be created.
    assert Path(cfg.cache_dir).exists()
