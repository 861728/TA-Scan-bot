from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeSnapshot:
    cycles_total: int
    alerts_sent: int
    ai_calls: int
    provider_source_count: int
    cache_source_count: int


class RuntimeMetrics:
    """In-memory runtime counters for health/observability."""

    def __init__(self) -> None:
        self._cycles_total = 0
        self._alerts_sent = 0
        self._ai_calls = 0
        self._provider_source_count = 0
        self._cache_source_count = 0

    def record_cycle(self, data_source: str, alert_sent: bool, ai_called: bool) -> None:
        self._cycles_total += 1
        if alert_sent:
            self._alerts_sent += 1
        if ai_called:
            self._ai_calls += 1
        if data_source == "provider":
            self._provider_source_count += 1
        elif data_source == "cache":
            self._cache_source_count += 1

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            cycles_total=self._cycles_total,
            alerts_sent=self._alerts_sent,
            ai_calls=self._ai_calls,
            provider_source_count=self._provider_source_count,
            cache_source_count=self._cache_source_count,
        )
