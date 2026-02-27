from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        return payload

    @staticmethod
    def from_dict(payload: dict) -> "Bar":
        return Bar(
            timestamp=normalize_timestamp(payload["timestamp"]),
            open=float(payload["open"]),
            high=float(payload["high"]),
            low=float(payload["low"]),
            close=float(payload["close"]),
            volume=float(payload["volume"]),
        )


@dataclass(frozen=True)
class CacheMetadata:
    symbol: str
    timeframe: str
    timezone: str
    start: datetime | None
    end: datetime | None
    bar_count: int

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timezone": self.timezone,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "bar_count": self.bar_count,
        }


def normalize_timestamp(ts: datetime | str) -> datetime:
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts)
    else:
        dt = ts

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class DataCache:
    """JSON file based cache for OHLCV bars."""

    def __init__(self, root_dir: str | Path = "data/cache") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, symbol: str, timeframe: str) -> Path:
        return self.root_dir / f"{symbol}_{timeframe}.json"

    def load(self, symbol: str, timeframe: str) -> list[Bar]:
        target = self._file_path(symbol, timeframe)
        if not target.exists():
            return []
        with target.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return [Bar.from_dict(item) for item in payload.get("bars", [])]

    def save(self, symbol: str, timeframe: str, bars: Iterable[Bar]) -> CacheMetadata:
        normalized = sorted(
            (self._normalize_bar(bar) for bar in bars), key=lambda x: x.timestamp
        )
        data = {
            "schema_version": 1,
            "symbol": symbol,
            "timeframe": timeframe,
            "timezone": "UTC",
            "bars": [bar.to_dict() for bar in normalized],
        }

        target = self._file_path(symbol, timeframe)
        with target.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return CacheMetadata(
            symbol=symbol,
            timeframe=timeframe,
            timezone="UTC",
            start=normalized[0].timestamp if normalized else None,
            end=normalized[-1].timestamp if normalized else None,
            bar_count=len(normalized),
        )

    @staticmethod
    def _normalize_bar(bar: Bar) -> Bar:
        return Bar(
            timestamp=normalize_timestamp(bar.timestamp),
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )


class DataLayer:
    """Data-layer operations: incremental merge, gap filling, timezone unification."""

    @staticmethod
    def timeframe_to_minutes(timeframe: str) -> int:
        if timeframe.endswith("m"):
            return int(timeframe[:-1])
        if timeframe.endswith("h"):
            return int(timeframe[:-1]) * 60
        if timeframe.endswith("d"):
            return int(timeframe[:-1]) * 60 * 24
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    def __init__(self, cache: DataCache) -> None:
        self.cache = cache

    def merge_incremental(self, existing: list[Bar], incoming: list[Bar]) -> list[Bar]:
        merged: dict[datetime, Bar] = {}
        for bar in existing:
            normalized = DataCache._normalize_bar(bar)
            merged[normalized.timestamp] = normalized
        for bar in incoming:
            normalized = DataCache._normalize_bar(bar)
            # latest data wins for same timestamp (incremental overwrite)
            merged[normalized.timestamp] = normalized
        return [merged[key] for key in sorted(merged.keys())]

    def fill_missing(
        self,
        bars: list[Bar],
        expected_interval_minutes: int = 15,
        max_gap_minutes: int = 60,
    ) -> list[Bar]:
        if not bars:
            return []

        ordered = sorted((DataCache._normalize_bar(b) for b in bars), key=lambda x: x.timestamp)
        if len(ordered) < 2:
            return ordered

        interval = expected_interval_minutes

        result: list[Bar] = [ordered[0]]
        for current in ordered[1:]:
            prev = result[-1]
            gap_minutes = int((current.timestamp - prev.timestamp).total_seconds() // 60)
            if gap_minutes > interval and gap_minutes <= max_gap_minutes:
                missing_steps = (gap_minutes // interval) - 1
                for step in range(1, missing_steps + 1):
                    ts = prev.timestamp + (current.timestamp - prev.timestamp) * (step / (missing_steps + 1))
                    # flat carry-forward for short data holes
                    result.append(
                        Bar(
                            timestamp=normalize_timestamp(ts),
                            open=prev.close,
                            high=prev.close,
                            low=prev.close,
                            close=prev.close,
                            volume=0.0,
                        )
                    )
            result.append(current)
        return sorted(result, key=lambda x: x.timestamp)

    def update_cache(
        self,
        symbol: str,
        timeframe: str,
        incoming_bars: list[Bar],
        max_gap_minutes: int = 60,
    ) -> CacheMetadata:
        existing = self.cache.load(symbol=symbol, timeframe=timeframe)
        merged = self.merge_incremental(existing=existing, incoming=incoming_bars)
        interval = self.timeframe_to_minutes(timeframe)
        repaired = self.fill_missing(
            merged,
            expected_interval_minutes=interval,
            max_gap_minutes=max_gap_minutes,
        )
        return self.cache.save(symbol=symbol, timeframe=timeframe, bars=repaired)
