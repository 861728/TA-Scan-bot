from __future__ import annotations

from datetime import datetime, timedelta
import json
from urllib import request as _urllib_request
from typing import Callable

from .data_layer import Bar, normalize_timestamp


class KRWConverter:
    """USD→KRW 환율 조회. open.er-api.com 무료 API 사용 (키 불필요). 10분 캐시."""

    _API_URL = "https://open.er-api.com/v6/latest/USD"

    def __init__(self, cache_minutes: int = 10, timeout: int = 5) -> None:
        self._cache_minutes = cache_minutes
        self._timeout = timeout
        self._rate: float | None = None
        self._fetched_at: datetime | None = None

    def get_rate(self) -> float | None:
        """현재 USD/KRW 환율 반환. 실패 시 None."""
        if self._rate and self._fetched_at:
            if datetime.utcnow() - self._fetched_at < timedelta(minutes=self._cache_minutes):
                return self._rate
        try:
            req = _urllib_request.Request(self._API_URL, headers={"Accept": "application/json"})
            with _urllib_request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
            self._rate = float(data["rates"]["KRW"])
            self._fetched_at = datetime.utcnow()
            return self._rate
        except Exception:
            return self._rate  # 실패 시 마지막 캐시 값 반환

    def convert(self, usd: float) -> float | None:
        rate = self.get_rate()
        return usd * rate if rate else None


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
