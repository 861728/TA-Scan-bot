from datetime import datetime
from zoneinfo import ZoneInfo

from m7_bottomfinder.notifiers import SafeNotifier, TelegramNotifier
from m7_bottomfinder.providers import YahooFinanceFetcher

UTC = ZoneInfo("UTC")


def test_yahoo_fetcher_with_injected_loader() -> None:
    def loader(symbol: str, timeframe: str, lookback: str) -> list[dict]:
        assert symbol == "AAPL"
        assert timeframe == "15m"
        assert lookback == "200d"
        return [
            {
                "timestamp": datetime(2026, 2, 1, tzinfo=UTC),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 1200,
            }
        ]

    fetcher = YahooFinanceFetcher(loader=loader)
    bars = fetcher("AAPL", "15m")
    assert len(bars) == 1
    assert bars[0].close == 100.5


def test_yahoo_fetcher_returns_empty_on_loader_failure() -> None:
    def broken(_s: str, _t: str, _p: str) -> list[dict]:
        raise RuntimeError("boom")

    fetcher = YahooFinanceFetcher(loader=broken)
    assert fetcher("AAPL", "15m") == []


def test_telegram_notifier_uses_post_function() -> None:
    calls: list[tuple[str, bytes, int]] = []

    def post(url: str, data: bytes, timeout: int) -> None:
        calls.append((url, data, timeout))

    n = TelegramNotifier("TOKEN", "CHAT", timeout_seconds=7, post=post)
    n.send("hello")

    assert len(calls) == 1
    assert "TOKEN" in calls[0][0]
    assert b"chat_id=CHAT" in calls[0][1]
    assert b"text=hello" in calls[0][1]
    assert calls[0][2] == 7


def test_safe_notifier_swallows_errors() -> None:
    class Broken:
        def send(self, text: str) -> None:
            raise RuntimeError(text)

    SafeNotifier(Broken()).send("x")
