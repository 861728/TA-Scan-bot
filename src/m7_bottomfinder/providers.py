from __future__ import annotations

from datetime import datetime
from typing import Callable

from .data_layer import Bar, normalize_timestamp


class YahooFinanceFetcher:
    """Best-effort yfinance fetcher. Returns [] on dependency/provider failures."""

    def __init__(
        self,
        lookback_period: str = "200d",
        loader: Callable[[str, str, str], list[dict]] | None = None,
    ) -> None:
        self.lookback_period = lookback_period
        self.loader = loader

    def __call__(self, symbol: str, timeframe: str) -> list[Bar]:
        try:
            if self.loader is not None:
                rows = self.loader(symbol, timeframe, self.lookback_period)
                return [self._row_to_bar(r) for r in rows]

            import yfinance as yf  # optional runtime dependency

            interval = self._map_timeframe(timeframe)
            hist = yf.Ticker(symbol).history(period=self.lookback_period, interval=interval)
            bars: list[Bar] = []
            for idx, row in hist.iterrows():
                bars.append(
                    Bar(
                        timestamp=normalize_timestamp(idx.to_pydatetime()),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row["Volume"]),
                    )
                )
            return bars
        except Exception:
            return []

    @staticmethod
    def _map_timeframe(timeframe: str) -> str:
        mapping = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
        return mapping.get(timeframe, timeframe)

    @staticmethod
    def _row_to_bar(row: dict) -> Bar:
        ts = row.get("timestamp")
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(str(ts))
        return Bar(
            timestamp=normalize_timestamp(ts),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0.0)),
        )
