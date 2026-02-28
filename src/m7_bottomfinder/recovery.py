from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .data_layer import Bar, DataCache


@dataclass(frozen=True)
class RecoveryResult:
    source: str
    bars: list[Bar]


class FetchRecovery:
    """Fetches fresh bars and falls back to cached bars on provider failure."""

    def __init__(self, cache: DataCache) -> None:
        self.cache = cache

    def fetch_with_fallback(
        self,
        symbol: str,
        timeframe: str,
        fetcher: Callable[[str, str], list[Bar]],
    ) -> RecoveryResult:
        try:
            bars = fetcher(symbol, timeframe)
            if bars:
                return RecoveryResult(source="provider", bars=bars)
        except Exception:
            pass
        return RecoveryResult(source="cache", bars=self.cache.load(symbol, timeframe))
